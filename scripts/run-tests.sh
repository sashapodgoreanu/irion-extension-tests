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

cleanup() {
  if [[ -n "${HTTPFS_SERVER_PID:-}" ]] && kill -0 "${HTTPFS_SERVER_PID}" 2>/dev/null; then
    kill "${HTTPFS_SERVER_PID}" || true
    wait "${HTTPFS_SERVER_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [[ "${TEST_NAME}" == "httpfs" ]]; then
  # shellcheck disable=SC1091
  source scripts/setup-httpfs.sh "${RUNTIME_ROOT}"
fi

INIT_SQL="INSTALL httpfs; INSTALL ducklake; LOAD httpfs; LOAD ducklake;"
CONNECTION_SQL="LOAD httpfs; LOAD ducklake;"
TEST_CONFIG="${RUNTIME_ROOT}/all-extensions.json"
EXTENSION_CSV="${LOG_DIR}/extensions.csv"

cat > "${TEST_CONFIG}" <<EOF
{
  "description": "HTTPFS and DuckLake compatibility runtime",
  "autoloading": "none",
  "on_init": "${INIT_SQL}",
  "on_new_connection": "${CONNECTION_SQL}",
  "summarize_failures": true
}
EOF

"${DUCKDB_BIN}" -csv -header -c "${INIT_SQL}
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
