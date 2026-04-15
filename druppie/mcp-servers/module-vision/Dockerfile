FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY module-vision/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared router factory and module code
COPY module_router.py .
COPY module-vision/ .

# Environment variables
ENV MCP_PORT=9011

EXPOSE 9011

CMD ["python", "server.py"]
