FROM python:3.11-slim

WORKDIR /app

# curl for the /health check
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY module-foundry/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Shared router factory + module code
COPY module_router.py .
COPY module-foundry/ .

ENV MCP_PORT=9012

EXPOSE 9012

CMD ["python", "server.py"]
