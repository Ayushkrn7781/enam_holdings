# Stage 1: build the SPA
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime serving the API and the built SPA
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=web /web/dist frontend/dist
ENV FRONTEND_DIST=/app/frontend/dist PORT=8000 FINN_DATA_DIR=/tmp/finn FINN_SNAPSHOT_DIR=/app/backend/seed \
    PYTHONUNBUFFERED=1
WORKDIR /app/backend
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn finn.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
