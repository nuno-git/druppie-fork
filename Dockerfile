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

# Install pinned helm + kubectl binaries. The branch-environments API runs
# `helm upgrade --install` (and kubectl for secret/namespace prep) as a subprocess
# from inside this pod to stand up per-branch Druppie stacks. Kept in the rarely-
# changing layers (above the code COPY) so the download stays cached across builds.
ARG HELM_VERSION=v3.16.4
ARG KUBECTL_VERSION=v1.31.3
RUN curl -fsSL "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" \
      | tar xz -C /tmp \
    && install -m 755 /tmp/linux-amd64/helm /usr/local/bin/helm \
    && rm -rf /tmp/linux-amd64 \
    && curl -fsSL -o /usr/local/bin/kubectl \
       "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
    && chmod +x /usr/local/bin/kubectl \
    && helm version --short \
    && kubectl version --client

# Install Python dependencies
COPY druppie/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Bust cache for source code layers (dependency layers above stay cached)
ARG CACHEBUST
# Copy application code
COPY druppie/ /app/druppie/

# Copy test definitions (YAML files for evaluation framework)
COPY testing/ /app/testing/

# Copy the Helm chart source. The branch-environments deployer runs
# `helm upgrade --install` against this path to create per-branch stacks.
# Build context is the repo root (.), so helm/ is available here.
COPY helm/ /app/helm/

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
# Where the branch-environments deployer finds the chart (stable in-image path).
ENV BRANCH_ENV_CHART_PATH=/app/helm/druppie

# Create workspace directory
RUN mkdir -p /app/workspace

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
# Single worker required: FallbackLLM approval state and TranslationService
# notification state are process-local. Multiple workers cause cross-worker
# desync (e.g. "Switch all agents" approval lost on round-robin).
CMD ["uvicorn", "druppie.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
