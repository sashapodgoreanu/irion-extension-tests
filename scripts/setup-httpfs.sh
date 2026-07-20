#!/usr/bin/env bash

HTTPFS_RUNTIME_ROOT="${1:?runtime directory is required}"
export PYTHON_HTTP_SERVER_DIR="${HTTPFS_RUNTIME_ROOT}/python-http"
export PYTHON_HTTP_SERVER_URL="http://127.0.0.1:8008"

mkdir -p "${PYTHON_HTTP_SERVER_DIR}"
python3 -m http.server 8008 \
  --bind 127.0.0.1 \
  --directory "${PYTHON_HTTP_SERVER_DIR}" \
  >"${HTTPFS_RUNTIME_ROOT}/python-http.log" 2>&1 &
export HTTPFS_SERVER_PID=$!

for _ in $(seq 1 30); do
  if python3 - <<'PY'
import socket
with socket.create_connection(("127.0.0.1", 8008), timeout=1):
    pass
PY
  then
    return 0 2>/dev/null || exit 0
  fi
  sleep 1
done

echo "HTTPFS Python server did not become ready" >&2
return 1 2>/dev/null || exit 1
