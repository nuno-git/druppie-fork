FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && \
    apt-get install -y curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create default data directory
RUN mkdir -p /data

ENV DATA_DIR=/data
ENV PYTHONUNBUFFERED=1

EXPOSE 9007

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:9007/health || exit 1

CMD ["python", "-u", "server.py"]
