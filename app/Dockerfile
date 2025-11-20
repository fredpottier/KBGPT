# Image de base avec CUDA 12.0 + Python 3.11 pour support GPU RTX 5070 Ti
FROM nvidia/cuda:12.0.0-base-ubuntu22.04

# Installer Python 3.11
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-dev \
    python3-pip \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Paris
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DISPLAY=:99 \
    LIBGL_ALWAYS_INDIRECT=1 \
    MESA_GL_VERSION_OVERRIDE=3.3

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-fra \
    fonts-dejavu-core \
    libglib2.0-0 \
    libgomp1 \
    libgl1 \
    libgl1-mesa-dri \
    mesa-utils \
    libsm6 \
    libxext6 \
    libxrender1 \
    libfontconfig1 \
    libxi6 \
    libxrandr2 \
    libegl1 \
    libgbm1 \
    xvfb \
    default-jre-headless \
    libreoffice-core \
    libreoffice-common \
    libreoffice-impress \
    libreoffice-java-common \
 && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

WORKDIR /app

# Optimisation pip
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Installation pip et outils de base
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Installation requirements (cache Docker si inchang??)
COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Pr??-t??l??chargement des packages NLTK pour ??viter les erreurs r??seau (unstructured dependencies)
RUN python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('punkt_tab', quiet=True); nltk.download('averaged_perceptron_tagger', quiet=True); nltk.download('averaged_perceptron_tagger_eng', quiet=True)" || echo "NLTK download failed, will try at runtime"

# Téléchargement modèles spaCy pour OSMOSE (Phase 1 V2.1)
# Modèles medium (md) pour documents techniques SAP/RFP
# Précision NER 85-90% vs 75-80% pour sm (+100 MB mais worth it pour RFP)
RUN python -m spacy download en_core_web_md || echo "spaCy en model download failed"
RUN python -m spacy download fr_core_news_md || echo "spaCy fr model download failed"
RUN python -m spacy download xx_ent_wiki_sm || echo "spaCy xx model download failed"

# Téléchargement modèle fasttext pour détection langue OSMOSE
RUN mkdir -p /app/models && \
    curl -L https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin -o /app/models/lid.176.bin || \
    echo "fasttext language model download failed (will use fallback)"

# Code application (à la fin pour optimiser cache Docker)
COPY src/knowbase/ /app/knowbase/
COPY app/main.py /app/main.py
COPY app/patch_unstructured.py /app/patch_unstructured.py
COPY app/claims_utils.py /app/claims_utils.py
COPY app/entrypoint-worker.sh /app/entrypoint-worker.sh
RUN chmod +x /app/entrypoint-worker.sh
RUN mkdir -p /app/config

ENV HF_HOME=/data/models
ENV KNOWBASE_DATA_DIR=/data
ENV PYTHONPATH="/app:/app/src"

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

