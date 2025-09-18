FROM python:3.11

ENV TZ=Europe/Paris
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libreoffice \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-fra \
    fonts-dejavu-core \
    libgl1 \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Préparation pip
RUN pip config set global.disable-pip-version-check true \
 && pip config set global.timeout 100 \
 && pip install --upgrade pip setuptools wheel \
 && pip cache purge

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade --retries 5 --timeout 60 -r /app/requirements.txt

RUN pip freeze

COPY . /app

ENV HF_HOME=/data/models
ENV KNOWBASE_DATA_DIR=/data
ENV PYTHONPATH="/app:$PYTHONPATH"

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
