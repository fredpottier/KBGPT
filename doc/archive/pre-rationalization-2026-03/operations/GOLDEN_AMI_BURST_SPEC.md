# Golden AMI - Mode Burst OSMOSE

## Objectif

Créer une AMI pré-configurée contenant tous les composants nécessaires pour le Mode Burst, permettant un démarrage quasi-instantané des instances Spot sans téléchargement de modèles.

## Avantages de l'approche Golden AMI

| Approche | Temps démarrage | Fiabilité | Coût |
|----------|-----------------|-----------|------|
| Userdata (actuel) | 10-15 min | Dépend de HuggingFace/Docker Hub | 0€/mois |
| Golden AMI | 1-2 min | Autonome | ~4€/mois (80GB) |

**Calcul coût stockage AMI :**
- EBS Snapshot : ~0.05$/GB/mois
- AMI 80GB : ~4$/mois

**Détail taille AMI :**
| Composant | Taille |
|-----------|--------|
| Système Ubuntu + drivers NVIDIA | ~40GB |
| Qwen 2.5 14B AWQ (quantifié) | ~8GB |
| E5-Large Embeddings | ~1.3GB |
| Image Docker vLLM | ~8GB |
| Image Docker TEI | ~2GB |
| Marge | ~5GB |
| **Total** | **~65GB → 80GB** |

---

## Spécifications de la Golden AMI

### 1. Base AMI

```
AMI de base : Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.5 (Ubuntu 22.04)
ID actuel   : ami-0f1273572a6a564a1 (eu-central-1)
Instance    : g6e.xlarge (L40S 24GB VRAM) - cible principale
Fallback    : g6.2xlarge, g5.2xlarge
```

### 2. Composants à pré-installer

#### 2.1 Docker Images (pré-pullées)

```bash
# vLLM OpenAI-compatible server
docker pull vllm/vllm-openai:latest
# Taille : ~8GB

# Text Embeddings Inference (HuggingFace)
docker pull ghcr.io/huggingface/text-embeddings-inference:1.5
# Taille : ~2GB
```

#### 2.2 Modèles LLM (pré-téléchargés)

```bash
# Modèle principal : Qwen 2.5 14B Instruct AWQ (quantifié)
# Chemin : /models/Qwen--Qwen2.5-14B-Instruct-AWQ/
# Taille : ~8GB
# Raison : Meilleur rapport qualité/taille pour extraction sémantique

# Alternative si besoin de plus petit :
# Qwen 2.5 7B Instruct AWQ (~4GB)
```

#### 2.3 Modèles Embeddings (pré-téléchargés)

```bash
# Modèle principal : intfloat/multilingual-e5-large
# Chemin : /models/intfloat--multilingual-e5-large/
# Taille : ~2GB
# Raison : Multilingue, performant, compatible avec notre pipeline

# Cache HuggingFace à configurer
export HF_HOME=/models
export TRANSFORMERS_CACHE=/models
```

### 3. Configuration Système

#### 3.1 Services systemd

```ini
# /etc/systemd/system/burst-vllm.service
[Unit]
Description=OSMOSE Burst vLLM Server
After=docker.service
Requires=docker.service

[Service]
Type=simple
Restart=always
RestartSec=10
ExecStartPre=/usr/bin/docker rm -f vllm 2>/dev/null || true
ExecStart=/usr/bin/docker run --rm --gpus all \
    -p 8000:8000 \
    --name vllm \
    -v /models:/root/.cache/huggingface \
    vllm/vllm-openai:latest \
    --model Qwen/Qwen2.5-14B-Instruct-AWQ \
    --quantization awq \
    --dtype half \
    --gpu-memory-utilization 0.85 \
    --max-model-len 8192 \
    --max-num-seqs 32 \
    --trust-remote-code
ExecStop=/usr/bin/docker stop vllm

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/burst-embeddings.service
[Unit]
Description=OSMOSE Burst Embeddings Server
After=docker.service
Requires=docker.service

[Service]
Type=simple
Restart=always
RestartSec=10
ExecStartPre=/usr/bin/docker rm -f embeddings 2>/dev/null || true
ExecStart=/usr/bin/docker run --rm --gpus all \
    -p 8001:80 \
    --name embeddings \
    -v /models:/data \
    ghcr.io/huggingface/text-embeddings-inference:1.5 \
    --model-id intfloat/multilingual-e5-large
ExecStop=/usr/bin/docker stop embeddings

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/burst-healthcheck.service
[Unit]
Description=OSMOSE Burst Healthcheck Aggregator
After=burst-vllm.service burst-embeddings.service

[Service]
Type=simple
Restart=always
ExecStart=/usr/bin/python3 /opt/burst/healthcheck.py

[Install]
WantedBy=multi-user.target
```

#### 3.2 Script Healthcheck

```python
# /opt/burst/healthcheck.py
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import json
import time

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        vllm_ok = emb_ok = False
        vllm_status = emb_status = "unknown"

        # Check vLLM
        try:
            with urllib.request.urlopen('http://localhost:8000/health', timeout=5) as r:
                vllm_ok = r.status == 200
                vllm_status = "ready" if vllm_ok else "starting"
        except Exception as e:
            vllm_status = str(e)

        # Check Embeddings
        try:
            with urllib.request.urlopen('http://localhost:8001/health', timeout=5) as r:
                emb_ok = r.status == 200
                emb_status = "ready" if emb_ok else "starting"
        except Exception as e:
            emb_status = str(e)

        ready = vllm_ok and emb_ok
        status_code = 200 if ready else 503

        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()

        response = {
            'ready': ready,
            'vllm': {'ok': vllm_ok, 'status': vllm_status},
            'embeddings': {'ok': emb_ok, 'status': emb_status},
            'timestamp': time.time()
        }
        self.wfile.write(json.dumps(response).encode())

    def log_message(self, *args):
        pass  # Silence logs

if __name__ == '__main__':
    print("Starting healthcheck server on port 8080...")
    HTTPServer(('', 8080), HealthHandler).serve_forever()
```

#### 3.3 Script de démarrage automatique

```bash
# /opt/burst/startup.sh
#!/bin/bash
# Script de démarrage Mode Burst

set -e

echo "[BURST] Starting OSMOSE Burst Mode..."
echo "[BURST] Timestamp: $(date -Iseconds)"

# Activer les services
systemctl start burst-vllm
systemctl start burst-embeddings
systemctl start burst-healthcheck

# Attendre que tout soit prêt
echo "[BURST] Waiting for services..."
for i in {1..60}; do
    if curl -s http://localhost:8080 | grep -q '"ready":true'; then
        echo "[BURST] All services ready!"
        break
    fi
    sleep 5
done

echo "[BURST] Startup complete at $(date -Iseconds)"
```

### 4. Structure des fichiers

```
/
├── models/                           # Modèles pré-téléchargés
│   ├── Qwen--Qwen2.5-14B-Instruct-AWQ/
│   │   ├── config.json
│   │   ├── model-*.safetensors
│   │   └── tokenizer.json
│   └── intfloat--multilingual-e5-large/
│       ├── config.json
│       ├── model.safetensors
│       └── tokenizer.json
│
├── opt/burst/                        # Scripts OSMOSE
│   ├── startup.sh
│   ├── healthcheck.py
│   └── config.env
│
└── etc/systemd/system/              # Services
    ├── burst-vllm.service
    ├── burst-embeddings.service
    └── burst-healthcheck.service
```

---

## Procédure de Création de la Golden AMI

### Étape 1 : Lancer une instance de base

```bash
# Créer une instance On-Demand (pas Spot) pour la configuration
aws ec2 run-instances \
    --region eu-central-1 \
    --image-id ami-0f1273572a6a564a1 \
    --instance-type g6e.xlarge \
    --key-name YOUR_KEY_NAME \
    --security-group-ids sg-XXXXXXXX \
    --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=80,VolumeType=gp3}" \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=burst-ami-builder}]'
```

### Étape 2 : Configurer l'instance (via SSH)

```bash
# 1. Mettre à jour le système
sudo apt update && sudo apt upgrade -y

# 2. Créer le répertoire des modèles
sudo mkdir -p /models
sudo chmod 777 /models

# 3. Télécharger les modèles LLM
pip install huggingface_hub
python3 -c "
from huggingface_hub import snapshot_download
# Modèle LLM
snapshot_download('Qwen/Qwen2.5-14B-Instruct-AWQ',
                  local_dir='/models/Qwen--Qwen2.5-14B-Instruct-AWQ',
                  local_dir_use_symlinks=False)
# Modèle Embeddings
snapshot_download('intfloat/multilingual-e5-large',
                  local_dir='/models/intfloat--multilingual-e5-large',
                  local_dir_use_symlinks=False)
"

# 4. Pull les images Docker
sudo docker pull vllm/vllm-openai:latest
sudo docker pull ghcr.io/huggingface/text-embeddings-inference:1.5

# 5. Créer les fichiers de configuration
sudo mkdir -p /opt/burst
# (copier les fichiers startup.sh, healthcheck.py, services systemd)

# 6. Activer les services au démarrage
sudo systemctl enable burst-vllm
sudo systemctl enable burst-embeddings
sudo systemctl enable burst-healthcheck

# 7. Tester le démarrage
sudo /opt/burst/startup.sh
curl http://localhost:8080  # Doit retourner ready:true

# 8. Arrêter les services avant création AMI
sudo systemctl stop burst-vllm burst-embeddings burst-healthcheck
sudo docker rm -f vllm embeddings 2>/dev/null || true

# 9. Nettoyer pour réduire la taille
sudo apt clean
sudo rm -rf /var/cache/apt/archives/*
sudo rm -rf /tmp/*
history -c
```

### Étape 3 : Créer l'AMI

```bash
# Depuis votre poste local
aws ec2 create-image \
    --region eu-central-1 \
    --instance-id i-XXXXXXXXX \
    --name "osmose-burst-golden-v1.0" \
    --description "OSMOSE Burst Mode - Qwen 2.5 14B AWQ + E5-Large Embeddings" \
    --tag-specifications 'ResourceType=image,Tags=[{Key=Project,Value=OSMOSE},{Key=Version,Value=1.0}]'
```

### Étape 4 : Terminer l'instance builder

```bash
aws ec2 terminate-instances --region eu-central-1 --instance-id i-XXXXXXXXX
```

---

## Utilisation de la Golden AMI

### Démarrage rapide Mode Burst

```bash
# 1. Lancer une instance Spot avec la Golden AMI
aws ec2 run-instances \
    --region eu-central-1 \
    --image-id ami-GOLDEN_AMI_ID \
    --instance-type g6e.xlarge \
    --security-group-ids sg-BURST_SG \
    --instance-market-options MarketType=spot \
    --user-data '#!/bin/bash
/opt/burst/startup.sh' \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=osmose-burst},{Key=Mode,Value=Burst}]'

# 2. Attendre ~1-2 min que les services démarrent

# 3. Vérifier le healthcheck
curl http://INSTANCE_IP:8080
# {"ready":true,"vllm":{"ok":true},"embeddings":{"ok":true}}
```

### Intégration avec KnowWhere

L'orchestrateur Burst (`src/knowbase/ingestion/burst/`) utilisera cette AMI via :

```python
# Dans burst_orchestrator.py
class BurstOrchestrator:
    def __init__(self, config: BurstConfig):
        self.golden_ami_id = config.golden_ami_id  # ami-XXXXXXXX
        self.instance_type = "g6e.xlarge"
        self.region = "eu-central-1"

    async def start_burst_instance(self):
        # Lancer instance Spot avec Golden AMI
        # Temps de démarrage attendu : 1-2 min vs 10-15 min
        pass
```

---

## Maintenance de la Golden AMI

### Mise à jour des modèles

Quand un nouveau modèle est disponible :

1. Lancer une instance depuis la Golden AMI actuelle
2. Mettre à jour les modèles
3. Créer une nouvelle AMI (v1.1, v1.2, etc.)
4. Mettre à jour la config OSMOSE
5. Supprimer l'ancienne AMI après validation

### Versioning recommandé

```
osmose-burst-golden-v1.0  # Initial - Qwen 2.5 14B AWQ
osmose-burst-golden-v1.1  # Mise à jour modèle
osmose-burst-golden-v2.0  # Changement majeur (nouveau LLM)
```

---

## Coûts estimés

| Élément | Coût |
|---------|------|
| Stockage AMI (80GB) | ~4€/mois |
| Instance Spot g6e.xlarge | ~1.17€/h (prix actuel) |
| **Prix max configuré** | **1.50€/h** |
| Transfert données | Variable |

**Stratégie de prix Spot :**
- Prix max limité à **1.50€/h** (vs 2.33€ On-Demand)
- Prix actuel : ~1.17€/h → marge de ~28%
- Si le prix dépasse 1.50€ → interruption avec 2 min préavis
- Le système de **resume automatique** reprend le traitement

**Comparaison avec approche actuelle :**
- Sans Golden AMI : 10-15 min de démarrage = ~0.25€ gaspillés par démarrage
- Avec Golden AMI : 1-2 min de démarrage = économie de temps + fiabilité

---

## Checklist de création

- [ ] Créer instance g6e.xlarge On-Demand avec 80GB
- [ ] Installer et configurer Docker
- [ ] Télécharger modèle Qwen 2.5 14B AWQ (~8GB)
- [ ] Télécharger modèle E5-Large Embeddings (~2GB)
- [ ] Pull images Docker (vllm, text-embeddings-inference)
- [ ] Créer services systemd
- [ ] Créer scripts startup et healthcheck
- [ ] Tester le démarrage complet
- [ ] Nettoyer l'instance
- [ ] Créer l'AMI
- [ ] Tester avec instance Spot
- [ ] Mettre à jour config OSMOSE avec AMI ID
- [ ] Supprimer instance builder

---

## Ressources

- [vLLM Documentation](https://docs.vllm.ai/)
- [Text Embeddings Inference](https://huggingface.co/docs/text-embeddings-inference/)
- [AWS EC2 AMI Creation](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/creating-an-ami-ebs.html)
- [Qwen 2.5 Models](https://huggingface.co/Qwen)

---

*Document créé le 2025-12-28 - OSMOSE KnowWhere Project*
