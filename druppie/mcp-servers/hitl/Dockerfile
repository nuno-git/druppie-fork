FROM python:3.11-slim

WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY server.py .

# Environment variables
ENV MCP_PORT=9003
ENV REDIS_URL=redis://redis:6379/0
ENV HITL_TIMEOUT=300
ENV BACKEND_URL=http://druppie-backend:8000
ENV INTERNAL_API_KEY=druppie-internal-key

EXPOSE 9003

CMD ["python", "server.py"]
