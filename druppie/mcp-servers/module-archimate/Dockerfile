FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y curl && \
    rm -rf /var/lib/apt/lists/*

COPY mcp-servers/module-archimate/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ARG CACHEBUST
COPY mcp-servers/module_router.py .
COPY mcp-servers/module-archimate/ .

COPY mcp-servers/module-archimate/models/ /models/

ENV MODELS_DIR=/models
ENV PYTHONUNBUFFERED=1

EXPOSE 9006

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:9006/health || exit 1

CMD ["python", "-u", "server.py"]
