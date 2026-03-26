FROM python:3.11-slim

WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy module code
COPY . .

# Create workspace directory
RUN mkdir -p /workspaces

# Environment variables
ENV WORKSPACE_ROOT=/workspaces
ENV MCP_PORT=9008

EXPOSE 9008

CMD ["python", "server.py"]
