FROM python:3.11-slim

WORKDIR /pack

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download GLiNER model
RUN python -c "from gliner import GLiNER; GLiNER.from_pretrained('urchade/gliner_medium-v2.1')" \
    || echo "Model download failed, will retry at runtime"

COPY server.py .
COPY context_defaults.json .

EXPOSE 9102

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9102", "--workers", "1"]
