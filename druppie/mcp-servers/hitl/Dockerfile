FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY server.py .

# Environment variables
ENV MCP_PORT=9003
ENV REDIS_URL=redis://redis:6379/0
ENV HITL_TIMEOUT=300

EXPOSE 9003

CMD ["python", "server.py"]
