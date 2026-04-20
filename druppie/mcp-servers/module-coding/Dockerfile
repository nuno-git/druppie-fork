FROM python:3.12-slim-bookworm

WORKDIR /app

# Install git, curl, Chromium, and Node.js 22 LTS (matching sandbox environment)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl chromium ca-certificates gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22 LTS (matching sandbox environment)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Configure Puppeteer to use system Chromium (skip bundled download)
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# Install Mermaid CLI for structural diagram validation
RUN npm install -g @mermaid-js/mermaid-cli

# Install dependencies
COPY module-coding/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared router factory and module code
COPY module_router.py .
COPY module-coding/ .

# Create workspace directory
RUN mkdir -p /workspaces

# Environment variables
ENV WORKSPACE_ROOT=/workspaces
ENV MCP_PORT=9001

EXPOSE 9001

CMD ["python", "server.py"]
