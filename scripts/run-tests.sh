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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_SCRIPT="${SCRIPT_DIR}/install-extensions.sql"
INIT_SCRIPT="${SCRIPT_DIR}/init-extensions.sql"
HTTPFS_AUTOLOAD_INIT_SCRIPT="${SCRIPT_DIR}/init-without-httpfs.sql"

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

EXTENSION_CSV="${LOG_DIR}/extensions.csv"
NORMAL_CONFIG="${RUNTIME_ROOT}/all-extensions.json"
HTTPFS_AUTOLOAD_CONFIG="${RUNTIME_ROOT}/httpfs-autoload.json"
CONNECTION_SQL="LOAD json; LOAD tpch; LOAD tpcds; LOAD icu; LOAD httpfs; LOAD ducklake;"
INSTALL_SQL="$(sed '/^[[:space:]]*--/d' "${INSTALL_SCRIPT}" | tr '\n' ' ')"
INIT_SQL="$(sed '/^[[:space:]]*--/d' "${INIT_SCRIPT}" | tr '\n' ' ')"

cat >"${NORMAL_CONFIG}" <<EOF
{
  "description": "HTTPFS and DuckLake compatibility runtime",
  "autoloading": "all",
  "init_script": "${INIT_SCRIPT}",
  "on_new_connection": "${CONNECTION_SQL}",
  "statically_loaded_extensions": [
    "core_functions",
    "parquet"
  ],
  "summarize_failures": true
}
EOF

cat >"${HTTPFS_AUTOLOAD_CONFIG}" <<EOF
{
  "description": "HTTPFS autoloading tests with DuckLake loaded",
  "autoloading": "all",
  "init_script": "${HTTPFS_AUTOLOAD_INIT_SCRIPT}",
  "on_new_connection": "LOAD tpcds; LOAD ducklake;",
  "statically_loaded_extensions": [
    "core_functions"
  ],
  "summarize_failures": true
}
EOF

cp "${NORMAL_CONFIG}" "${LOG_DIR}/all-extensions.json"
cp "${HTTPFS_AUTOLOAD_CONFIG}" "${LOG_DIR}/httpfs-autoload.json"
cp "${INSTALL_SCRIPT}" "${LOG_DIR}/install-extensions.sql"
cp "${INIT_SCRIPT}" "${LOG_DIR}/init-extensions.sql"
cp "${HTTPFS_AUTOLOAD_INIT_SCRIPT}" "${LOG_DIR}/init-without-httpfs.sql"

{
  echo "test_name=${TEST_NAME}"
  echo "test_path=${TEST_PATH}"
  echo "upstream_commit=$(git -C "${UPSTREAM_ROOT}" rev-parse HEAD)"
} >"${LOG_DIR}/test-info.txt"

"${DUCKDB_BIN}" -csv -header -c "${INSTALL_SQL} ${INIT_SQL}
  SELECT extension_name, installed, loaded, extension_version, install_mode, installed_from
  FROM duckdb_extensions()
  WHERE extension_name IN ('ducklake', 'httpfs', 'icu', 'json', 'tpcds', 'tpch')
  ORDER BY extension_name;" \
  | tee "${EXTENSION_CSV}"

python3 - "${EXTENSION_CSV}" <<'PY'
import csv
import sys
from pathlib import Path

rows = list(csv.DictReader(Path(sys.argv[1]).open(encoding="utf-8")))
by_name = {row["extension_name"]: row for row in rows}
for name in ("ducklake", "httpfs", "icu", "json", "tpcds", "tpch"):
    row = by_name.get(name)
    if not row:
        raise SystemExit(f"{name} is missing from duckdb_extensions()")
    if row.get("installed", "").lower() != "true":
        raise SystemExit(f"{name} is not installed")
    if row.get("loaded", "").lower() != "true":
        raise SystemExit(f"{name} is not loaded")
PY

run_suite() {
  local label=$1
  local config=$2
  local filter=$3
  local log_file="${LOG_DIR}/unittest-${label}.log"

  "${UNITTEST_BIN}" \
    --test-config "${config}" \
    --test-dir "${UPSTREAM_ROOT}" \
    "${filter}" \
    2>&1 | tee "${log_file}"

  if grep -Eq '^require (ducklake|httpfs|icu|json|tpcds|tpch): [1-9][0-9]*$' "${log_file}"; then
    echo "Required extensions were skipped by the DuckDB test runner in ${label}" >&2
    grep -E '^require (ducklake|httpfs|icu|json|tpcds|tpch): ' "${log_file}" >&2 || true
    exit 1
  fi
}

if [[ "${TEST_NAME}" == "httpfs" ]]; then
  # Normal HTTPFS SQL tests run with HTTPFS and DuckLake explicitly loaded.
  run_suite "sql" "${NORMAL_CONFIG}" "test/sql/*"

  # HTTPFS lifecycle tests must start with HTTPFS unloaded; otherwise their
  # autoload/autoinstall assertions become invalid. DuckLake remains loaded.
  run_suite "autoload" "${HTTPFS_AUTOLOAD_CONFIG}" "test/extension/*"
else
  run_suite "all" "${NORMAL_CONFIG}" "${TEST_PATH}"
fi
