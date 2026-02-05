# Druppie Platform - FastAPI Backend
# Build context: project root (.)
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY druppie/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY druppie/ /app/druppie/

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Create workspace directory
RUN mkdir -p /app/workspace

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "druppie.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
