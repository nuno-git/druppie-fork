FROM python:3.11-slim

WORKDIR /app

# Install Docker CLI
RUN apt-get update && \
    apt-get install -y curl && \
    curl -fsSL https://get.docker.com | sh && \
    rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY . .

# Environment variables
ENV MCP_PORT=9002
ENV DOCKER_NETWORK=druppie-new-network

EXPOSE 9002

CMD ["python", "server.py"]
