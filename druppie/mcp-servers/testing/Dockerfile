FROM python:3.11-slim

WORKDIR /app

# Install system dependencies + Node.js (for JS/TS test frameworks)
RUN apt-get update && \
    apt-get install -y curl git gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY server.py .
COPY module.py .

# Environment variables
ENV MCP_PORT=9005
ENV WORKSPACE_ROOT=/workspaces

EXPOSE 9005

CMD ["python", "server.py"]