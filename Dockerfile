# Druppie Platform - FastAPI Backend
# Build context: project root (.)
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (incl. Node.js, npm, Chromium for pre-approval
# Mermaid validation via mmdc — mirrors mcp-servers/coding/Dockerfile)
RUN apt-get update && apt-get install -y \
    git \
    curl \
    docker.io \
    nodejs \
    npm \
    chromium \
    && rm -rf /var/lib/apt/lists/*

# Configure Puppeteer to use system Chromium (skip bundled download)
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# Install Mermaid CLI for structural diagram validation
RUN npm install -g @mermaid-js/mermaid-cli

# Install Python dependencies
COPY druppie/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY druppie/ /app/druppie/

# Copy and build the vendored pi_agent (execute_coding_task_pi). Runs as
# a child subprocess of this backend container — node + docker.io are
# already installed above. Each invocation spawns its own sysbox/kata
# sandbox; parallelism is bounded only by the backend container's CPU.
COPY pi_agent/package.json pi_agent/package-lock.json /app/pi_agent/
RUN cd /app/pi_agent && npm ci --ignore-scripts || npm install --ignore-scripts
COPY pi_agent/ /app/pi_agent/
RUN cd /app/pi_agent && rm -rf dist && npx tsc && npm prune --omit=dev

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PI_AGENT_ROOT=/app/pi_agent
ENV PI_AGENT_SESSIONS_DIR=/app/pi_agent_sessions

# Create workspace + pi_agent sessions dirs
RUN mkdir -p /app/workspace /app/pi_agent_sessions

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "druppie.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
