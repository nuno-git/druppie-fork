FROM python:3.11-slim

WORKDIR /app

# curl for the HEALTHCHECK. Chromium's OS deps (libnss, fonts, ...) are
# installed by `playwright install --with-deps chromium` below.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

COPY module-browser/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install --with-deps chromium

ARG CACHEBUST
# Copy shared router factory and module code
COPY module_router.py .
COPY module-browser/ .

ENV PYTHONUNBUFFERED=1

EXPOSE 9015

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:9015/health || exit 1

CMD ["python", "-u", "server.py"]
