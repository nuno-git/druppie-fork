FROM python:3.11-slim

WORKDIR /app

# Install git, curl, Node.js/npm, and Chromium for git operations, health checks,
# JS test runners, and Mermaid diagram validation (mmdc needs a browser via Puppeteer)
RUN apt-get update && apt-get install -y git curl nodejs npm chromium && rm -rf /var/lib/apt/lists/*

# Configure Puppeteer to use system Chromium (skip bundled download)
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# Install Mermaid CLI for structural diagram validation
RUN npm install -g @mermaid-js/mermaid-cli

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY . .

# Create workspace directory
RUN mkdir -p /workspaces

# Environment variables
ENV WORKSPACE_ROOT=/workspaces
ENV MCP_PORT=9001

EXPOSE 9001

CMD ["python", "server.py"]
