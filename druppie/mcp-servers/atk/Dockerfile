FROM python:3.11-slim

WORKDIR /app

# Install Node.js 20 (required for ATK CLI)
RUN apt-get update && \
    apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install ATK CLI globally
RUN npm install -g @microsoft/m365agentstoolkit-cli

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY server.py .

# Environment variables
ENV MCP_PORT=9010
ENV ATK_PROJECTS_DIR=/atk-projects

EXPOSE 9010

CMD ["python", "server.py"]
