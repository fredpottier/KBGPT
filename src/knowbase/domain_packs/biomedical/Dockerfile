FROM python:3.11-slim

WORKDIR /pack

# Dépendances système minimales pour spaCy
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Installer les modèles NER scispaCy
RUN pip install --no-cache-dir \
    https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bc5cdr_md-0.5.4.tar.gz \
    https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bionlp13cg_md-0.5.4.tar.gz

# Code du serveur
COPY server.py .
COPY context_defaults.json .

EXPOSE 9100

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9100", "--workers", "1"]
