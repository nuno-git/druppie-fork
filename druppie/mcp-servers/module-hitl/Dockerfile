FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && \
    apt-get install -y curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Environment variables
ENV MCP_PORT=9003
ENV HITL_TIMEOUT=300
ENV BACKEND_URL=http://druppie-backend:8000
ENV INTERNAL_API_KEY=druppie-internal-key
ENV PYTHONUNBUFFERED=1

EXPOSE 9003

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:9003/health || exit 1

CMD ["python", "-u", "server.py"]
