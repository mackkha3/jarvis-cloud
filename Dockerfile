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

COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
