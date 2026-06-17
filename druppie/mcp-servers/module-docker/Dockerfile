FROM python:3.11-slim

WORKDIR /app

# Install Docker CLI
RUN apt-get update && \
    apt-get install -y curl && \
    curl -fsSL https://get.docker.com | sh && \
    rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY module-docker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared router factory and module code
COPY module_router.py .
COPY module-docker/ .

# Environment variables
ENV MCP_PORT=9002
ENV DOCKER_NETWORK=druppie-new-network

EXPOSE 9002

CMD ["python", "server.py"]
