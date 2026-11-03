# One container: builds the React app, then serves it and the API from FastAPI on $PORT.
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app/backend
ENV PYTHONUNBUFFERED=1 FRONTEND_DIST=/app/frontend/dist PORT=8000 \
    FINN_DATA_DIR=/tmp/finn FINN_SNAPSHOT_DIR=/app/backend/seed
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
# On start: restore backend/seed (prebuilt demo or your live snapshot); otherwise build the demo dataset.
EXPOSE 8000
CMD uvicorn finn.api.app:app --host 0.0.0.0 --port ${PORT}
