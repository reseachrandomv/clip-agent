FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-dejavu-core \
        fontconfig \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "from faster_whisper.utils import download_model; download_model('base')"

COPY app ./app
COPY static ./static

ENV DATA_DIR=/data \
    PORT=8000 \
    PYTHONUNBUFFERED=1 \
    WHISPER_MODEL=base \
    HF_HUB_ETAG_TIMEOUT=5 \
    HF_HUB_DOWNLOAD_TIMEOUT=30

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
