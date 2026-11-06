#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
if [ ! -x .venv/bin/python ]; then
  echo '请先按README安装已锁定依赖。' >&2
  exit 1
fi
exec .venv/bin/python -m uvicorn app.pilot:app --host 127.0.0.1 --port "${PILOT_PORT:-18430}" --no-access-log
