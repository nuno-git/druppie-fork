FROM python:3.11-slim

WORKDIR /app

# Install git, curl, and Node.js/npm for git operations, health checks, and JS test runners
RUN apt-get update && apt-get install -y git curl nodejs npm && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY server.py .
COPY module.py .
COPY testing_module.py .
COPY mermaid_validator.py .

# Create workspace directory
RUN mkdir -p /workspaces

# Environment variables
ENV WORKSPACE_ROOT=/workspaces
ENV MCP_PORT=9001

EXPOSE 9001

CMD ["python", "server.py"]
