#!/bin/bash
exec > /var/log/burst.log 2>&1
set -ex
echo "=== BURST ===" && date
systemctl start docker && systemctl enable docker
docker pull vllm/vllm-openai:latest &
docker pull ghcr.io/huggingface/text-embeddings-inference:1.5 &
wait
docker run -d --gpus all -p 8000:8000 --name vllm vllm/vllm-openai:latest --model Qwen/Qwen2.5-14B-Instruct-AWQ --quantization awq --dtype half --gpu-memory-utilization 0.85 --max-model-len 8192 --max-num-seqs 32 --trust-remote-code
docker run -d --gpus all -p 8001:80 --name emb ghcr.io/huggingface/text-embeddings-inference:1.5 --model-id intfloat/multilingual-e5-large
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