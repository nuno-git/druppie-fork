FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && \
    apt-get install -y curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY module.py .

# Create default models directory
RUN mkdir -p /models

ENV MODELS_DIR=/models
ENV PYTHONUNBUFFERED=1

EXPOSE 9006

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:9006/health || exit 1

CMD ["python", "-u", "server.py"]
