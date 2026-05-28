FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY module-notificatie/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared router factory and module code
COPY module_router.py .
COPY module-notificatie/ .

# Environment variables
ENV MCP_PORT=9202

EXPOSE 9202

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:9202/health || exit 1

CMD ["python", "server.py"]
