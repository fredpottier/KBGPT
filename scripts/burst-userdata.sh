#!/bin/bash
exec > /var/log/burst.log 2>&1
set -ex
echo "=== BURST ===" && date
systemctl start docker && systemctl enable docker
docker pull vllm/vllm-openai:v0.9.2 &
docker pull ghcr.io/huggingface/text-embeddings-inference:1.5 &
wait

# Patch AWQ Marlin (bug vLLM v0.9.2 : user_quant="awq" non reconnu pour Marlin)
mkdir -p /opt/burst/patches
docker create --name vllm-temp vllm/vllm-openai:v0.9.2
docker cp vllm-temp:/usr/local/lib/python3.12/dist-packages/vllm/model_executor/layers/quantization/awq_marlin.py /opt/burst/patches/awq_marlin.py
docker rm vllm-temp
python3 -c "
p='/opt/burst/patches/awq_marlin.py'
c=open(p).read()
old='or user_quant == \"awq_marlin\")'
new='or user_quant == \"awq_marlin\"\n                            or user_quant == \"awq\")'
if old in c and 'or user_quant == \"awq\")' not in c:
    open(p,'w').write(c.replace(old,new))
    print('[BURST] Patched awq_marlin.py')
"

docker run -d --gpus all -p 8000:8000 --name vllm \
  -v /opt/burst/patches/awq_marlin.py:/usr/local/lib/python3.12/dist-packages/vllm/model_executor/layers/quantization/awq_marlin.py:ro \
  vllm/vllm-openai:v0.9.2 --model Qwen/Qwen3-14B-AWQ --quantization awq_marlin --dtype half --gpu-memory-utilization 0.85 --max-model-len 32768 --max-num-seqs 32 --trust-remote-code --reasoning-parser qwen3
# TEI avec limites augmentées (évite 413 Payload Too Large)
# --max-client-batch-size: max inputs par requête (défaut: 32 → 64)
# --max-batch-tokens: max tokens par batch (défaut: 16384 → 32768)
# --payload-limit: taille max body HTTP en bytes (défaut: 2MB → 10MB)
docker run -d --gpus all -p 8001:80 --name emb ghcr.io/huggingface/text-embeddings-inference:1.5 --model-id intfloat/multilingual-e5-large --max-client-batch-size 64 --max-batch-tokens 32768 --payload-limit 10000000
python3 -c "
from http.server import HTTPServer,BaseHTTPRequestHandler
import urllib.request,json
class H(BaseHTTPRequestHandler):
 def do_GET(self):
  v=e=False
  try:
   with urllib.request.urlopen('http://localhost:8000/health',timeout=5) as r:v=r.status==200
  except:pass
  try:
   with urllib.request.urlopen('http://localhost:8001/health',timeout=5) as r:e=r.status==200
  except:pass
  self.send_response(200 if v and e else 503);self.send_header('Content-Type','application/json');self.end_headers()
  self.wfile.write(json.dumps({'vllm':v,'emb':e,'ready':v and e}).encode())
 def log_message(self,*a):pass
HTTPServer(('',8080),H).serve_forever()
" &
echo "=== DONE ===" && date