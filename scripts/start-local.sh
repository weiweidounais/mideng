#!/bin/sh
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_ROOT/frontend"
if [ ! -d node_modules ]; then npm ci --no-audit --no-fund; fi
npm run build
cd "$PROJECT_ROOT/backend"
uv sync --frozen --python 3.12
exec uv run --no-sync uvicorn app.pilot:app --host 127.0.0.1 --port "${MIDENG_PORT:-18430}" --no-access-log
