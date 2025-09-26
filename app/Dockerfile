FROM python:3.11-slim

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
    libreoffice-core-nogui \
    libreoffice-common \
    libreoffice-impress-nogui \
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

# Code application (?? la fin pour optimiser cache Docker)
COPY app/ /app/
RUN mkdir -p /app/config

ENV HF_HOME=/data/models
ENV KNOWBASE_DATA_DIR=/data
ENV PYTHONPATH="/app:$PYTHONPATH"

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

