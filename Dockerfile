# Druppie Platform - FastAPI Backend
# Build context: project root (.)
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (incl. Node.js, npm, Chromium for pre-approval
# Mermaid validation via mmdc — mirrors mcp-servers/coding/Dockerfile)
RUN apt-get update && apt-get install -y \
    git \
    curl \
    ca-certificates \
    fontconfig \
    docker.io \
    nodejs \
    npm \
    chromium \
    && rm -rf /var/lib/apt/lists/*

# Install mermaid-cli globally for PDF Mermaid diagram rendering
RUN npm install -g @mermaid-js/mermaid-cli \
    && mmdc --version

# Install Typst (static Rust binary) for document formatting
RUN curl -L -o /tmp/typst.tar.xz \
    "https://github.com/typst/typst/releases/latest/download/typst-x86_64-unknown-linux-musl.tar.xz" \
    && tar -xJf /tmp/typst.tar.xz -C /tmp \
    && mv /tmp/typst-x86_64-unknown-linux-musl/typst /usr/local/bin/typst \
    && chmod +x /usr/local/bin/typst \
    && rm -rf /tmp/typst.tar.xz /tmp/typst-x86_64-unknown-linux-musl \
    && typst --version

# Configure Puppeteer to use system Chromium (skip bundled download)
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# Install Mermaid CLI for structural diagram validation
RUN npm install -g @mermaid-js/mermaid-cli

# Install Python dependencies
COPY druppie/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy application code
COPY druppie/ /app/druppie/

# Copy test definitions (YAML files for evaluation framework)
COPY testing/ /app/testing/

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV TYPST_FONT_PATHS=/app/druppie/templates/documents/assets/fonts

# Create workspace directory
RUN mkdir -p /app/workspace

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "druppie.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
