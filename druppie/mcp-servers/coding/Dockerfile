FROM python:3.11-slim

WORKDIR /app

# Install git for git operations
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY server.py .

# Create workspace directory
RUN mkdir -p /workspaces

# Environment variables
ENV WORKSPACE_ROOT=/workspaces
ENV MCP_PORT=9001

EXPOSE 9001

CMD ["python", "server.py"]
