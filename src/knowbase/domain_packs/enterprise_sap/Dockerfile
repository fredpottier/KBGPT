FROM python:3.11-slim

WORKDIR /pack

# Dependances systeme minimales
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# PyTorch CPU-only (evite les binaires CUDA, economie ~1GB)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Dependances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-telecharger le modele GLiNER dans l'image (cache HuggingFace)
RUN python -c "from gliner import GLiNER; GLiNER.from_pretrained('urchade/gliner_medium-v2.1')"

# Code du serveur
COPY server.py .
COPY context_defaults.json .

EXPOSE 9101

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9101", "--workers", "1"]
