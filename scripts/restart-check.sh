#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/backend/.venv/bin/python" "$ROOT/scripts/restart_check.py" "$@"
