# Druppie Platform - FastAPI Backend
# Build context: project root (.)
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    ca-certificates \
    fontconfig \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Install Typst (static Rust binary) for document formatting
RUN curl -L -o /tmp/typst.tar.xz \
    "https://github.com/typst/typst/releases/latest/download/typst-x86_64-unknown-linux-musl.tar.xz" \
    && tar -xJf /tmp/typst.tar.xz -C /tmp \
    && mv /tmp/typst-x86_64-unknown-linux-musl/typst /usr/local/bin/typst \
    && chmod +x /usr/local/bin/typst \
    && rm -rf /tmp/typst.tar.xz /tmp/typst-x86_64-unknown-linux-musl \
    && typst --version

# Install Python dependencies
COPY druppie/requirements.txt .
RUN pip install -r requirements.txt

# Bust cache for source code layers (dependency layers above stay cached)
ARG CACHEBUST
# Copy application code
COPY druppie/ /app/druppie/

# Copy test definitions (YAML files for evaluation framework)
COPY testing/ /app/testing/

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV TYPST_FONT_PATHS=/app/druppie/templates/documents/assets/fonts

# Create workspace and tmp directories
RUN mkdir -p /app/workspace /app/tmp

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
