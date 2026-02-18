#!/bin/bash
# =============================================================================
# OSMOSE Golden AMI - Script d'installation Mode Burst
# =============================================================================
# Ce script configure une instance EC2 pour devenir la Golden AMI Burst
# A executer en tant que root (sudo -i)
# =============================================================================

set -e

echo "=============================================="
echo "  OSMOSE Golden AMI - Installation Burst"
echo "=============================================="
echo ""

# -----------------------------------------------------------------------------
# 1. Mise a jour systeme
# -----------------------------------------------------------------------------
echo "[1/7] Mise a jour du systeme..."
apt-get update
apt-get upgrade -y
echo "OK - Systeme mis a jour"

# -----------------------------------------------------------------------------
# 2. Creation des repertoires
# -----------------------------------------------------------------------------
echo ""
echo "[2/7] Creation des repertoires..."
mkdir -p /models
mkdir -p /opt/burst
chmod 755 /models /opt/burst
echo "OK - Repertoires crees"

# -----------------------------------------------------------------------------
# 3. Telechargement des modeles
# -----------------------------------------------------------------------------
echo ""
echo "[3/7] Telechargement des modeles (peut prendre 10-15 min)..."

# Installer huggingface_hub si pas present
pip install -q huggingface_hub

# Telecharger Qwen3 14B AWQ
echo "  - Telechargement Qwen3 14B AWQ (~8GB)..."
python3 << 'EOF'
from huggingface_hub import snapshot_download
import os

# Modele LLM
print("    Downloading Qwen/Qwen2.5-14B-Instruct-AWQ...")
snapshot_download(
    "Qwen/Qwen2.5-14B-Instruct-AWQ",
    local_dir="/models/Qwen--Qwen2.5-14B-Instruct-AWQ",
    local_dir_use_symlinks=False
)
print("    Done!")

# Modele Embeddings
print("    Downloading intfloat/multilingual-e5-large...")
snapshot_download(
    "intfloat/multilingual-e5-large",
    local_dir="/models/intfloat--multilingual-e5-large",
    local_dir_use_symlinks=False
)
print("    Done!")
EOF

echo "OK - Modeles telecharges"

# -----------------------------------------------------------------------------
# 4. Pull des images Docker
# -----------------------------------------------------------------------------
echo ""
echo "[4/7] Pull des images Docker..."

echo "  - vLLM OpenAI (~8GB)..."
docker pull vllm/vllm-openai:v0.9.2

echo "  - Text Embeddings Inference (~2GB)..."
docker pull ghcr.io/huggingface/text-embeddings-inference:1.5

echo "OK - Images Docker pullees"

# -----------------------------------------------------------------------------
# 4b. Patch vLLM AWQ Marlin (contournement bug vLLM v0.9.2)
# -----------------------------------------------------------------------------
# vLLM v0.9.2 ne reconnait pas user_quant="awq" comme candidat Marlin.
# Le modele Qwen3-14B-AWQ a quant_method="awq" dans config.json, donc
# override_quantization_method() refuse l'upgrade vers awq_marlin.
# Ce patch ajoute "or user_quant == 'awq'" pour forcer l'activation Marlin.
# Resultat: ~26 t/s au lieu de ~3 t/s (8.5x speedup confirme).
echo ""
echo "[4b/7] Patch vLLM AWQ Marlin activation..."
mkdir -p /opt/burst/patches

# Extraire le fichier original depuis l'image Docker
docker create --name vllm-temp vllm/vllm-openai:v0.9.2 2>/dev/null
docker cp vllm-temp:/usr/local/lib/python3.12/dist-packages/vllm/model_executor/layers/quantization/awq_marlin.py /opt/burst/patches/awq_marlin.py
docker rm vllm-temp

# Appliquer le patch
python3 << 'PATCH_SCRIPT'
path = "/opt/burst/patches/awq_marlin.py"
with open(path) as f:
    code = f.read()

old = 'or user_quant == "awq_marlin")'
new = 'or user_quant == "awq_marlin"\n                            or user_quant == "awq")'

if old in code and 'or user_quant == "awq")' not in code:
    with open(path, 'w') as f:
        f.write(code.replace(old, new))
    print("  OK - awq_marlin.py patched for Marlin kernel activation")
else:
    print("  INFO - awq_marlin.py already patched or upstream fix applied")
PATCH_SCRIPT

echo "OK - Patch AWQ Marlin pret"

# -----------------------------------------------------------------------------
# 5. Creation des services systemd
# -----------------------------------------------------------------------------
echo ""
echo "[5/7] Creation des services systemd..."

# Service vLLM
cat > /etc/systemd/system/burst-vllm.service << 'VLLM_SERVICE'
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
    -e HF_HOME=/root/.cache/huggingface \
    -v /opt/burst/patches/awq_marlin.py:/usr/local/lib/python3.12/dist-packages/vllm/model_executor/layers/quantization/awq_marlin.py:ro \
    vllm/vllm-openai:v0.9.2 \
    --model Qwen/Qwen3-14B-AWQ \
    --quantization awq_marlin \
    --dtype half \
    --gpu-memory-utilization 0.85 \
    --max-model-len 32768 \
    --max-num-seqs 32 \
    --trust-remote-code \
    --reasoning-parser qwen3
ExecStop=/usr/bin/docker stop vllm

[Install]
WantedBy=multi-user.target
VLLM_SERVICE

# Service Embeddings
cat > /etc/systemd/system/burst-embeddings.service << 'EMB_SERVICE'
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
    --model-id /data/intfloat--multilingual-e5-large
ExecStop=/usr/bin/docker stop embeddings

[Install]
WantedBy=multi-user.target
EMB_SERVICE

# Service Healthcheck
cat > /etc/systemd/system/burst-healthcheck.service << 'HC_SERVICE'
[Unit]
Description=OSMOSE Burst Healthcheck Aggregator
After=burst-vllm.service burst-embeddings.service

[Service]
Type=simple
Restart=always
ExecStart=/usr/bin/python3 /opt/burst/healthcheck.py

[Install]
WantedBy=multi-user.target
HC_SERVICE

systemctl daemon-reload
echo "OK - Services systemd crees"

# -----------------------------------------------------------------------------
# 6. Script healthcheck
# -----------------------------------------------------------------------------
echo ""
echo "[6/7] Creation du script healthcheck..."

cat > /opt/burst/healthcheck.py << 'HEALTHCHECK'
#!/usr/bin/env python3
"""OSMOSE Burst Healthcheck Aggregator - Port 8080"""
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
            vllm_status = f"error: {type(e).__name__}"

        # Check Embeddings
        try:
            with urllib.request.urlopen('http://localhost:8001/health', timeout=5) as r:
                emb_ok = r.status == 200
                emb_status = "ready" if emb_ok else "starting"
        except Exception as e:
            emb_status = f"error: {type(e).__name__}"

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
        self.wfile.write(json.dumps(response, indent=2).encode())

    def log_message(self, *args):
        pass

if __name__ == '__main__':
    print("OSMOSE Burst Healthcheck starting on port 8080...")
    HTTPServer(('', 8080), HealthHandler).serve_forever()
HEALTHCHECK

chmod +x /opt/burst/healthcheck.py
echo "OK - Healthcheck cree"

# -----------------------------------------------------------------------------
# 7. Script de demarrage
# -----------------------------------------------------------------------------
echo ""
echo "[7/7] Creation du script de demarrage..."

cat > /opt/burst/startup.sh << 'STARTUP'
#!/bin/bash
# OSMOSE Burst Startup Script
echo "[BURST] Starting OSMOSE Burst Mode..."
echo "[BURST] Timestamp: $(date -Iseconds)"

systemctl start burst-vllm
systemctl start burst-embeddings
systemctl start burst-healthcheck

echo "[BURST] Services started, waiting for readiness..."
for i in {1..60}; do
    if curl -s http://localhost:8080 2>/dev/null | grep -q '"ready": true'; then
        echo "[BURST] All services ready!"
        exit 0
    fi
    echo "[BURST] Waiting... ($i/60)"
    sleep 5
done

echo "[BURST] Warning: Services may not be fully ready"
STARTUP

chmod +x /opt/burst/startup.sh

# Activer les services au demarrage
systemctl enable burst-vllm
systemctl enable burst-embeddings
systemctl enable burst-healthcheck

echo "OK - Scripts de demarrage crees"

# -----------------------------------------------------------------------------
# Resume
# -----------------------------------------------------------------------------
echo ""
echo "=============================================="
echo "  INSTALLATION TERMINEE"
echo "=============================================="
echo ""
echo "Modeles installes:"
ls -la /models/
echo ""
echo "Images Docker:"
docker images | grep -E "vllm|text-embeddings"
echo ""
echo "Services systemd:"
systemctl list-unit-files | grep burst
echo ""
echo "=============================================="
echo "  PROCHAINES ETAPES"
echo "=============================================="
echo ""
echo "1. Tester le demarrage des services:"
echo "   /opt/burst/startup.sh"
echo ""
echo "2. Verifier le healthcheck:"
echo "   curl http://localhost:8080"
echo ""
echo "3. Tester vLLM:"
echo "   curl http://localhost:8000/v1/models"
echo ""
echo "4. Si tout fonctionne, ARRETER les services avant AMI:"
echo "   systemctl stop burst-vllm burst-embeddings burst-healthcheck"
echo "   docker rm -f vllm embeddings 2>/dev/null"
echo ""
echo "5. Nettoyer avant creation AMI:"
echo "   apt-get clean"
echo "   rm -rf /var/cache/apt/archives/*"
echo "   rm -rf /tmp/*"
echo "   history -c"
echo ""
