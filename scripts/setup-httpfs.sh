#!/usr/bin/env bash

HTTPFS_RUNTIME_ROOT="${1:?runtime directory is required}"
HTTPFS_UPSTREAM_ROOT="${2:?HTTPFS upstream directory is required}"
HTTPFS_LOG_DIR="${HTTPFS_LOG_DIR:-${HTTPFS_RUNTIME_ROOT}/services}"

export PYTHON_HTTP_SERVER_DIR="${HTTPFS_RUNTIME_ROOT}/python-http"
export PYTHON_HTTP_SERVER_URL="http://127.0.0.1:8008"
export HTTP_PROXY_PUBLIC="127.0.0.1:3128"
export TEST_PERSISTENT_SECRETS_AVAILABLE=true

mkdir -p "${PYTHON_HTTP_SERVER_DIR}" "${HTTPFS_LOG_DIR}"

if [[ -d "${HTTPFS_UPSTREAM_ROOT}/data/secrets" ]]; then
  chmod -R 700 "${HTTPFS_UPSTREAM_ROOT}/data/secrets"
fi

python3 -m http.server 8008 \
  --bind 127.0.0.1 \
  --directory "${PYTHON_HTTP_SERVER_DIR}" \
  >"${HTTPFS_LOG_DIR}/python-http.log" 2>&1 &
export HTTPFS_SERVER_PID=$!

(
  cd "${HTTPFS_UPSTREAM_ROOT}"
  ./scripts/run_squid.sh \
    --port 3128 \
    --log_dir "${HTTPFS_LOG_DIR}/squid"
) >"${HTTPFS_LOG_DIR}/squid-process.log" 2>&1 &
export HTTPFS_SQUID_PID=$!

wait_for_port() {
  local port=$1
  local name=$2

  for _ in $(seq 1 60); do
    if python3 - "${port}" <<'PY'
import socket
import sys

with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=1):
    pass
PY
    then
      return 0
    fi
    sleep 1
  done

  echo "${name} did not become ready on port ${port}" >&2
  return 1
}

wait_for_port 8008 "HTTPFS Python server"
wait_for_port 3128 "HTTPFS Squid proxy"

for host in \
  duckdb-minio.com \
  test-bucket.duckdb-minio.com \
  test-bucket-2.duckdb-minio.com \
  test-bucket-public.duckdb-minio.com; do
  if ! grep -Eq "(^|[[:space:]])${host}([[:space:]]|$)" /etc/hosts; then
    echo "127.0.0.1 ${host}" | sudo tee -a /etc/hosts >/dev/null
  fi
done

(
  cd "${HTTPFS_UPSTREAM_ROOT}"
  ./scripts/generate_presigned_url.sh
)

pushd "${HTTPFS_UPSTREAM_ROOT}" >/dev/null
# These scripts belong to the pinned HTTPFS revision and define its MinIO test environment.
# shellcheck disable=SC1091
source ./scripts/run_s3_test_server.sh
# shellcheck disable=SC1091
source ./scripts/set_s3_test_server_variables.sh
popd >/dev/null

export HTTPFS_MINIO_STARTED=1
