FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y curl && \
    rm -rf /var/lib/apt/lists/*

COPY mcp-servers/module-registry/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ARG CACHEBUST
COPY mcp-servers/module_router.py .
COPY mcp-servers/module-registry/ .

COPY agents/definitions/ /data/agents/
COPY core/mcp_config.yaml /data/mcp_config.yaml
COPY skills/ /data/skills/
COPY agents/builtin_tools.py /data/builtin_tools.py
COPY mcp-servers/ /data/mcp-servers/

ENV DATA_DIR=/data
ENV PYTHONUNBUFFERED=1

EXPOSE 9007

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:9007/health || exit 1

CMD ["python", "-u", "server.py"]
