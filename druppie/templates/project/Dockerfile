# Stage 1: Build frontend
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ .
RUN npm run build

# Stage 2: Python backend
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY druppie-sdk/ /tmp/druppie-sdk/
RUN pip install --no-cache-dir /tmp/druppie-sdk/
COPY app/ ./app/
COPY --from=frontend /build/dist ./static/
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "300", "app:create_app()"]
