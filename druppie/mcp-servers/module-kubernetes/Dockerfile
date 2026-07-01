FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY module-kubernetes/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ARG CACHEBUST
COPY module_router.py .
COPY module-kubernetes/ .

ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:9013/health || exit 1

CMD ["python", "server.py"]
