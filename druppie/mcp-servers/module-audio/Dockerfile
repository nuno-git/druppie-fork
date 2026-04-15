FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY module-audio/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared router factory and module code
COPY module_router.py .
COPY module-audio/ .

# Environment variables
ENV MCP_PORT=9012

EXPOSE 9012

CMD ["python", "server.py"]
