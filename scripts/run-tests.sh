#!/usr/bin/env bash
set -Eeuo pipefail

TEST_NAME="${1:?test name is required}"
UPSTREAM_ROOT="${2:?upstream root is required}"
TEST_PATH="${3:?test path is required}"
ARTIFACT_DIR="${ARTIFACT_DIR:-build/artifact}"

DUCKDB_BIN="${ARTIFACT_DIR}/bin/duckdb"
UNITTEST_BIN="${ARTIFACT_DIR}/bin/unittest"
RUNTIME_ROOT="${RUNNER_TEMP:-${PWD}/build/runtime}/${TEST_NAME}"
LOG_DIR="${PWD}/build/logs/${TEST_NAME}"

mkdir -p "${RUNTIME_ROOT}/home" "${RUNTIME_ROOT}/tmp" "${LOG_DIR}"
export HOME="${RUNTIME_ROOT}/home"
export TMPDIR="${RUNTIME_ROOT}/tmp"
export PATH="$(cd "$(dirname "${DUCKDB_BIN}")" && pwd):${PATH}"
export HTTPFS_LOG_DIR="${LOG_DIR}/services"

cleanup() {
  if [[ "${HTTPFS_MINIO_STARTED:-0}" == "1" ]]; then
    mkdir -p "${HTTPFS_LOG_DIR}"
    (
      cd "${UPSTREAM_ROOT}"
      docker compose -f scripts/minio_s3.yml -p duckdb-minio logs --no-color
    ) >"${HTTPFS_LOG_DIR}/minio.log" 2>&1 || true
    (
      cd "${UPSTREAM_ROOT}"
      docker compose -f scripts/minio_s3.yml -p duckdb-minio down --volumes --remove-orphans
    ) >>"${HTTPFS_LOG_DIR}/minio.log" 2>&1 || true
  fi

  for pid in "${HTTPFS_SQUID_PID:-}" "${HTTPFS_SERVER_PID:-}"; do
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" || true
      wait "${pid}" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT

if [[ "${TEST_NAME}" == "httpfs" ]]; then
  # shellcheck disable=SC1091
  source scripts/setup-httpfs.sh "${RUNTIME_ROOT}" "${UPSTREAM_ROOT}"
fi

# json and tpch are the additional test dependencies used by the upstream HTTPFS CI.
# They are installed as official binaries, not compiled by this repository.
PREFLIGHT_SQL="INSTALL json; INSTALL tpch; INSTALL httpfs; INSTALL ducklake; LOAD httpfs; LOAD ducklake;"
TEST_INIT_SQL="LOAD httpfs; LOAD ducklake;"
TEST_CONFIG="${RUNTIME_ROOT}/all-extensions.json"
EXTENSION_CSV="${LOG_DIR}/extensions.csv"

cat > "${TEST_CONFIG}" <<EOF
{
  "description": "HTTPFS and DuckLake compatibility runtime",
  "autoloading": "none",
  "statically_loaded_extensions": ["core_functions", "parquet"],
  "on_init": "${TEST_INIT_SQL}",
  "on_new_connection": "",
  "summarize_failures": true
}
EOF
cp "${TEST_CONFIG}" "${LOG_DIR}/all-extensions.json"

{
  echo "test_name=${TEST_NAME}"
  echo "test_path=${TEST_PATH}"
  echo "upstream_commit=$(git -C "${UPSTREAM_ROOT}" rev-parse HEAD)"
} > "${LOG_DIR}/test-info.txt"

"${DUCKDB_BIN}" -csv -header -c "${PREFLIGHT_SQL}
  SELECT extension_name, installed, loaded, extension_version, install_mode, installed_from
  FROM duckdb_extensions()
  WHERE extension_name IN ('httpfs', 'ducklake')
  ORDER BY extension_name;" \
  | tee "${EXTENSION_CSV}"

python3 - "${EXTENSION_CSV}" <<'PY'
import csv
import sys
from pathlib import Path

rows = list(csv.DictReader(Path(sys.argv[1]).open(encoding="utf-8")))
by_name = {row["extension_name"]: row for row in rows}
for name in ("httpfs", "ducklake"):
    row = by_name.get(name)
    if not row:
        raise SystemExit(f"{name} is missing from duckdb_extensions()")
    if row.get("installed", "").lower() != "true":
        raise SystemExit(f"{name} is not installed")
    if row.get("loaded", "").lower() != "true":
        raise SystemExit(f"{name} is not loaded")
PY

"${UNITTEST_BIN}" \
  --test-config "${TEST_CONFIG}" \
  --test-dir "${UPSTREAM_ROOT}" \
  "${TEST_PATH}" \
  2>&1 | tee "${LOG_DIR}/unittest.log"
