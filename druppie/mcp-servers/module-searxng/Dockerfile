FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && \
    apt-get install -y curl && \
    rm -rf /var/lib/apt/lists/*

COPY module-searxng/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ARG CACHEBUST
# Copy shared router factory and module code
COPY module_router.py .
COPY module-searxng/ .

ENV PYTHONUNBUFFERED=1

EXPOSE 9014

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:9014/health || exit 1

CMD ["python", "-u", "server.py"]
