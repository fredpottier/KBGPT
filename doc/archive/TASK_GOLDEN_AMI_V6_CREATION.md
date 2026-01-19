# Tâche: Création Golden AMI v6 pour Burst Mode

**Date**: 2026-01-11
**Priorité**: Haute
**Statut**: À faire

## Contexte

Le 2026-01-11, les instances EC2 Burst ont commencé à échouer avec l'erreur "Services not ready within 900s".

**Investigation révèle:**
- L'AMI Golden v5 (`ami-04235317b5d52f6c3`) ne contient PAS le container vLLM
- Seul le container `embeddings` est présent sur l'instance
- Le UserData attend que les containers auto-démarrent mais ne les crée pas s'ils sont absents

**Mystère non résolu:**
- Le système fonctionnait les jours/semaines précédents avec le même AMI ID
- Aucun changement de code détecté dans git
- Possibilités: AMI corrompue, recréée côté AWS, ou autre problème

## Objectif

Créer une nouvelle Golden AMI v6 avec:
1. Container vLLM correctement configuré
2. Container Embeddings (TEI) correctement configuré
3. Services systemd OU containers avec `--restart unless-stopped`
4. Test complet avant snapshot

## Checklist de création

### Étape 1: Lancer instance de base
```bash
aws ec2 run-instances \
    --region eu-central-1 \
    --image-id ami-0f1273572a6a564a1 \  # Deep Learning AMI Ubuntu 22.04
    --instance-type g6.2xlarge \
    --key-name osmose-burst-key3 \
    --security-group-ids sg-XXXXXXXX \
    --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=100,VolumeType=gp3}" \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=osmose-ami-builder-v6}]'
```

### Étape 2: Configuration SSH
```bash
ssh -i config/osmose-burst-key3.pem ubuntu@<IP>
```

### Étape 3: Préparation système
- [ ] `sudo apt update && sudo apt upgrade -y`
- [ ] Créer répertoire modèles: `sudo mkdir -p /models && sudo chmod 777 /models`
- [ ] Vérifier GPU: `nvidia-smi`

### Étape 4: Télécharger modèles
```bash
pip install huggingface_hub
python3 << 'EOF'
from huggingface_hub import snapshot_download

# Modèle LLM (Qwen 2.5 14B AWQ)
snapshot_download('Qwen/Qwen2.5-14B-Instruct-AWQ',
                  local_dir='/models/Qwen--Qwen2.5-14B-Instruct-AWQ',
                  local_dir_use_symlinks=False)

# Modèle Embeddings (E5-Large)
snapshot_download('intfloat/multilingual-e5-large',
                  local_dir='/models/intfloat--multilingual-e5-large',
                  local_dir_use_symlinks=False)
EOF
```

### Étape 5: Pull images Docker
```bash
sudo docker pull vllm/vllm-openai:latest
sudo docker pull ghcr.io/huggingface/text-embeddings-inference:cpu-1.6
```

### Étape 6: Créer et tester les containers

**Option A - Containers avec restart policy (plus simple):**
```bash
# vLLM
sudo docker run -d --gpus all --restart unless-stopped \
    -p 8000:8000 --name vllm \
    -v /models:/root/.cache/huggingface \
    vllm/vllm-openai:latest \
    --model Qwen/Qwen2.5-14B-Instruct-AWQ \
    --quantization awq \
    --dtype half \
    --gpu-memory-utilization 0.70 \
    --max-model-len 8192 \
    --max-num-seqs 32 \
    --trust-remote-code

# Embeddings (TEI)
sudo docker run -d --restart unless-stopped \
    -p 8001:80 --name embeddings \
    -v /models:/data \
    ghcr.io/huggingface/text-embeddings-inference:cpu-1.6 \
    --model-id intfloat/multilingual-e5-large
```

**Option B - Services systemd (plus robuste):**
Voir `doc/specs/GOLDEN_AMI_BURST_SPEC.md` pour les fichiers systemd.

### Étape 7: Vérifier le fonctionnement
```bash
# Attendre ~8-10 min pour vLLM
watch -n 10 'curl -s http://localhost:8000/health; echo; docker logs vllm --tail 5'

# Test vLLM
curl http://localhost:8000/v1/models

# Test Embeddings
curl http://localhost:8001/health
```

### Étape 8: Test de redémarrage
```bash
# CRITIQUE: Tester que les containers redémarrent après reboot
sudo reboot

# Après reboot, vérifier:
docker ps  # Les deux containers doivent être running
curl http://localhost:8000/health
curl http://localhost:8001/health
```

### Étape 9: Créer l'AMI
```bash
# NE PAS arrêter les containers - laisser running pour --restart unless-stopped
# OU si systemd, stopper proprement

# Nettoyer
sudo apt clean
sudo rm -rf /var/cache/apt/archives/* /tmp/*
history -c

# Depuis poste local:
aws ec2 create-image \
    --region eu-central-1 \
    --instance-id i-XXXXXXXXX \
    --name "osmose-burst-golden-v6" \
    --description "OSMOSE Burst Mode v6 - Qwen 2.5 14B AWQ + E5-Large (2026-01-12)" \
    --tag-specifications 'ResourceType=image,Tags=[{Key=Project,Value=OSMOSE},{Key=Version,Value=6.0}]'
```

### Étape 10: Mettre à jour la configuration

Fichier: `src/knowbase/ingestion/burst/cloudformation/burst-spot.yaml`
```yaml
AmiId:
  Type: String
  Default: "ami-NOUVEAU_ID"  # <- Remplacer
  Description: AMI ID (Golden v6 avec Qwen 14B AWQ + TEI)
```

### Étape 11: Tester avec une vraie instance Burst
- [ ] Lancer depuis UI admin
- [ ] Vérifier que vLLM ET embeddings sont healthy
- [ ] Tester un import de document

### Étape 12: Cleanup
```bash
# Terminer l'instance builder
aws ec2 terminate-instances --region eu-central-1 --instance-id i-XXXXXXXXX

# Supprimer l'ancienne AMI v5 (après validation)
aws ec2 deregister-image --region eu-central-1 --image-id ami-04235317b5d52f6c3
```

## Points d'attention

1. **NE PAS faire `docker rm` avant le snapshot** - sinon les containers ne seront pas dans l'AMI
2. **Tester le reboot AVANT de créer l'AMI** - pour confirmer que les containers redémarrent
3. **Utiliser g6.2xlarge** (L4 24GB) - moins cher que g6e, suffisant pour 14B AWQ
4. **Vérifier les logs vLLM** - le chargement prend ~8-10 min

## Fichiers de référence

- Spec complète: `doc/specs/GOLDEN_AMI_BURST_SPEC.md`
- Template CloudFormation: `src/knowbase/ingestion/burst/cloudformation/burst-spot.yaml`
- Orchestrator: `src/knowbase/ingestion/burst/orchestrator.py`

## Investigation à faire (optionnel)

Pour comprendre pourquoi v5 fonctionnait avant:
1. Vérifier l'historique de l'AMI dans AWS Console (date création, modifications)
2. Chercher des logs CloudWatch des anciennes instances
3. Vérifier si une autre AMI a été utilisée accidentellement

---
*Document créé le 2026-01-11 - OSMOSE KnowWhere Project*
