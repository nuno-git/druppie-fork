FROM python:3.11-slim

WORKDIR /app

# Microsoft ODBC Driver 18 is required by pyodbc for Azure SQL / Synapse.
# python:3.11-slim is Debian 12 (bookworm), so use the bookworm prod repo.
RUN apt-get update && apt-get install -y --no-install-recommends \
        unixodbc-dev gcc curl gnupg ca-certificates \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

COPY module-data-access/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY module_router.py .
COPY module-data-access/ .

ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:9010/health || exit 1

CMD ["python", "server.py"]