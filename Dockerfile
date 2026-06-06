FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    FRONTEND_DIST_PATH=/app/frontend/dist

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin fovea \
    && mkdir -p /data/fovea/assets \
    && chown -R fovea:fovea /data/fovea

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY --from=frontend-builder /build/frontend/dist /app/frontend/dist
COPY docker/entrypoint.sh /app/docker/entrypoint.sh

RUN chmod +x /app/docker/entrypoint.sh \
    && chown -R fovea:fovea /app

USER fovea

EXPOSE 8080

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

