FROM python:3.11-slim

# System deps — libsndfile1 + ffmpeg for future Kokoro TTS/audio layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer-cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Ensure writable dirs exist for logs (Railway filesystem is ephemeral but
# the app expects these dirs to be present at startup)
RUN mkdir -p logs pwa/icons

# Railway injects PORT at runtime; default to 8080 for local Docker runs
EXPOSE 8080

# Shell form so ${PORT:-8080} expands correctly at container start
CMD gunicorn run:app \
    --bind "0.0.0.0:${PORT:-8080}" \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --log-level info
