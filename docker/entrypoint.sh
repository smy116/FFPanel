#!/bin/sh
set -eu

mkdir -p "${FFPANEL_CONFIG_DIR:-/config}" "${FFPANEL_CACHE_DIR:-/cache}"
alembic upgrade head
exec uvicorn ffpanel.main:app --host "${FFPANEL_HOST:-0.0.0.0}" --port "${FFPANEL_PORT:-8080}" --workers 1

