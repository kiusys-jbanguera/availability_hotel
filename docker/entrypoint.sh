#!/bin/sh
# Sin argumentos levanta la API (HU-S02 RF-06); con argumentos ejecuta el
# comando recibido (por ejemplo `docker run <imagen> id -u`).
set -eu

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

exec uvicorn availability_hotel.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --no-access-log \
    --timeout-keep-alive 5 \
    --timeout-graceful-shutdown 10
