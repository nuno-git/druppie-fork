FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY module-objectstore/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared router factory and module code
COPY module_router.py .
COPY module-objectstore/ .

# Environment variables
ENV MCP_PORT=9204

EXPOSE 9204

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:9204/health || exit 1

CMD ["python", "server.py"]
