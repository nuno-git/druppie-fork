FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY module-llm/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared router factory and module code
COPY module_router.py .
COPY module-llm/ .

# Environment variables
ENV MCP_PORT=9008

EXPOSE 9008

CMD ["python", "server.py"]
