#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
exec "$ROOT/backend/.venv/bin/python" "$ROOT/scripts/verify_integration.py"
