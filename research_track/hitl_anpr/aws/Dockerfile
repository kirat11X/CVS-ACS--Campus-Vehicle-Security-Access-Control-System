# Training image for an EC2 GPU instance (g6.2xlarge, NVIDIA L4). The NVIDIA driver comes from the host
# (Deep Learning Base AMI); the CUDA 13 runtime comes from the pinned torch wheels.
# Build from research_track/hitl_anpr:  docker build -f aws/Dockerfile -t campus-anpr-hitl:$(git rev-parse --short HEAD) .
# Pin the base image by digest before relying on rebuilds (`docker pull python:3.12-slim-bookworm` shows it).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    YOLO_OFFLINE=1 YOLO_SETTINGS_SYNC=False
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 tesseract-ocr ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 anpr
WORKDIR /app
COPY requirements.lock ./
RUN pip install --extra-index-url https://download.pytorch.org/whl/cu130 -r requirements.lock
COPY pyproject.toml config.yaml MODEL_CARD_TEMPLATE.md ./
COPY src ./src
RUN pip install --no-deps -e .
USER anpr
# The private data root is mounted at /data (synced from the encrypted bucket by aws/user_data.sh).
ENTRYPOINT ["anpr", "--data-root", "/data"]
