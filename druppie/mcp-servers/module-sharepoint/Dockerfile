FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY module-sharepoint/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY module_router.py .
COPY module-sharepoint/ .

ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:9014/health || exit 1

CMD ["python", "server.py"]
