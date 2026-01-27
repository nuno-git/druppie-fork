FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

# Create default dataset directory
RUN mkdir -p /dataset

ENV SEARCH_ROOT=/dataset
ENV PYTHONUNBUFFERED=1

EXPOSE 9004

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9004/health')" || exit 1

CMD ["python", "-u", "server.py"]
