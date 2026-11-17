# ==============================================================================
# CVS-ACS Backend Production Dockerfile
# Multi-stage / Optimized Python 3.12 Slim Image for FastAPI & Background Workers
# ==============================================================================

FROM python:3.12-slim-bookworm AS base

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

# Install system dependencies (OpenCV, Tesseract OCR, FFmpeg, PostgreSQL runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgl1 \
    libglib2.0-0 \
    tesseract-ocr \
    tesseract-ocr-eng \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create application user
RUN useradd -m -u 1001 campus

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy application source code and configurations
COPY alembic.ini ./alembic.ini
COPY alembic/ ./alembic/
COPY backend/ ./backend/
COPY config/ ./config/
COPY weights/ ./weights/

# Ensure directory permissions for runtime logs and uploads
RUN mkdir -p /app/media /app/logs && chown -R campus:campus /app

USER campus

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--log-level", "info"]
