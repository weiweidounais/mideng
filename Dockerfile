FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy LANGSMITH_TRACING=false
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/app ./app
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations
COPY --from=frontend /build/dist /app/frontend/dist
RUN mkdir -p /data && useradd -u 10001 -M app && chown -R app:app /app /data
USER app
ENV DATA_DIR=/data
EXPOSE 8000
CMD ["uv","run","--no-sync","uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
