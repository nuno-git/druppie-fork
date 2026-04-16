FROM python:3.11-slim

WORKDIR /app

# Install Node.js 22 (required for @z_ai/mcp-server)
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY module-vision/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-install Z.AI MCP server
RUN npx -y @z_ai/mcp-server --help 2>/dev/null || true

# Copy shared router factory and module code
COPY module_router.py .
COPY module-vision/ .

# Environment variables
ENV MCP_PORT=9011

EXPOSE 9011

CMD ["python", "server.py"]
