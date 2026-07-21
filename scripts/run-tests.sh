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
DUCKLAKE_DEFAULT_INIT_SCRIPT="${SCRIPT_DIR}/init-ducklake-default.sql"
DUCKLAKE_AUTOLOAD_INIT_SCRIPT="${SCRIPT_DIR}/init-ducklake-autoload.sql"
HTTPFS_AUTOLOAD_INIT_SCRIPT="${SCRIPT_DIR}/init-without-httpfs.sql"
DUCKLAKE_CONFIG_HELPER="${SCRIPT_DIR}/prepare-ducklake-config.py"

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

  if [[ "${DUCKLAKE_POSTGRES_STARTED:-0}" == "1" ]]; then
    mkdir -p "${LOG_DIR}/services"
    docker logs ducklake-postgres >"${LOG_DIR}/services/postgres.log" 2>&1 || true
    docker rm -f ducklake-postgres >/dev/null 2>&1 || true
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
DUCKLAKE_AUTOLOAD_CONFIG="${RUNTIME_ROOT}/ducklake-autoload.json"
DUCKLAKE_SQLITE_CONFIG="${RUNTIME_ROOT}/ducklake-sqlite.json"
DUCKLAKE_POSTGRES_CONFIG="${RUNTIME_ROOT}/ducklake-postgres.json"
FULL_CONNECTION_SQL="LOAD json; LOAD tpch; LOAD tpcds; LOAD icu; LOAD httpfs; LOAD ducklake; LOAD postgres_scanner; LOAD sqlite_scanner; LOAD mssql;"
DUCKLAKE_DEFAULT_CONNECTION_SQL="LOAD json; LOAD tpch; LOAD tpcds; LOAD icu; LOAD httpfs; LOAD ducklake; LOAD mssql;"
DUCKLAKE_AUTOLOAD_CONNECTION_SQL="LOAD json; LOAD tpch; LOAD tpcds; LOAD icu; LOAD ducklake; LOAD mssql;"
HTTPFS_AUTOLOAD_CONNECTION_SQL="LOAD tpcds; LOAD ducklake; LOAD postgres_scanner; LOAD sqlite_scanner; LOAD mssql;"
INSTALL_SQL="$(sed '/^[[:space:]]*--/d' "${INSTALL_SCRIPT}" | tr '\n' ' ')"
INIT_SQL="$(sed '/^[[:space:]]*--/d' "${INIT_SCRIPT}" | tr '\n' ' ')"

if [[ "${TEST_NAME}" == "ducklake" ]]; then
  NORMAL_INIT_SCRIPT="${DUCKLAKE_DEFAULT_INIT_SCRIPT}"
  NORMAL_CONNECTION_SQL="${DUCKLAKE_DEFAULT_CONNECTION_SQL}"
  NORMAL_SKIP_TESTS=',
  "skip_tests": [
    {
      "reason": "Executed by the dedicated DuckLake autoloading suite",
      "paths": [
        "test/sql/autoloading/autoload_data_path.test"
      ]
    },
    {
      "reason": "Executed by the dedicated PostgreSQL catalog suite",
      "paths": [
        "test/sql/metadata/ducklake_settings_postgres.test",
        "test/sql/data_inlining/postgres_identifier_limit.test"
      ]
    },
    {
      "reason": "Executed by the dedicated SQLite catalog suite",
      "paths": [
        "test/sql/metadata/ducklake_settings_sqlite.test"
      ]
    }
  ]'
elif [[ "${TEST_NAME}" == "httpfs" ]]; then
  NORMAL_INIT_SCRIPT="${INIT_SCRIPT}"
  NORMAL_CONNECTION_SQL="${FULL_CONNECTION_SQL}"
  NORMAL_SKIP_TESTS=',
  "skip_tests": [
    {
      "reason": "Requires TPC-DS answer fixtures that are not present in the standalone HTTPFS checkout",
      "paths": [
        "test/sql/copy/s3/parquet_s3_tpcds.test_slow"
      ]
    }
  ]'
else
  NORMAL_INIT_SCRIPT="${INIT_SCRIPT}"
  NORMAL_CONNECTION_SQL="${FULL_CONNECTION_SQL}"
  NORMAL_SKIP_TESTS=""
fi

cat >"${NORMAL_CONFIG}" <<EOF
{
  "description": "HTTPFS, DuckLake and MSSQL compatibility runtime",
  "autoloading": "all",
  "init_script": "${NORMAL_INIT_SCRIPT}",
  "on_new_connection": "${NORMAL_CONNECTION_SQL}",
  "statically_loaded_extensions": [
    "core_functions",
    "parquet"
  ],
  "summarize_failures": true${NORMAL_SKIP_TESTS}
}
EOF

cat >"${HTTPFS_AUTOLOAD_CONFIG}" <<EOF
{
  "description": "HTTPFS autoloading tests with DuckLake and MSSQL loaded",
  "autoloading": "all",
  "init_script": "${HTTPFS_AUTOLOAD_INIT_SCRIPT}",
  "on_new_connection": "${HTTPFS_AUTOLOAD_CONNECTION_SQL}",
  "statically_loaded_extensions": [
    "core_functions"
  ],
  "summarize_failures": true
}
EOF

cat >"${DUCKLAKE_AUTOLOAD_CONFIG}" <<EOF
{
  "description": "DuckLake filesystem autoloading test with HTTPFS initially unloaded and MSSQL loaded",
  "autoloading": "all",
  "init_script": "${DUCKLAKE_AUTOLOAD_INIT_SCRIPT}",
  "on_new_connection": "${DUCKLAKE_AUTOLOAD_CONNECTION_SQL}",
  "statically_loaded_extensions": [
    "core_functions",
    "parquet"
  ],
  "summarize_failures": true
}
EOF

cp "${NORMAL_CONFIG}" "${LOG_DIR}/all-extensions.json"
cp "${HTTPFS_AUTOLOAD_CONFIG}" "${LOG_DIR}/httpfs-autoload.json"
cp "${DUCKLAKE_AUTOLOAD_CONFIG}" "${LOG_DIR}/ducklake-autoload.json"
cp "${INSTALL_SCRIPT}" "${LOG_DIR}/install-extensions.sql"
cp "${INIT_SCRIPT}" "${LOG_DIR}/init-extensions.sql"
cp "${DUCKLAKE_DEFAULT_INIT_SCRIPT}" "${LOG_DIR}/init-ducklake-default.sql"
cp "${DUCKLAKE_AUTOLOAD_INIT_SCRIPT}" "${LOG_DIR}/init-ducklake-autoload.sql"
cp "${HTTPFS_AUTOLOAD_INIT_SCRIPT}" "${LOG_DIR}/init-without-httpfs.sql"

{
  echo "test_name=${TEST_NAME}"
  echo "test_path=${TEST_PATH}"
  echo "upstream_commit=$(git -C "${UPSTREAM_ROOT}" rev-parse HEAD)"
} >"${LOG_DIR}/test-info.txt"

"${DUCKDB_BIN}" -csv -header -c "${INSTALL_SQL} ${INIT_SQL}
  SELECT extension_name, installed, loaded, extension_version, install_mode, installed_from
  FROM duckdb_extensions()
  WHERE extension_name IN ('ducklake', 'httpfs', 'icu', 'json', 'mssql', 'postgres_scanner', 'sqlite_scanner', 'tpcds', 'tpch')
  ORDER BY extension_name;" \
  | tee "${EXTENSION_CSV}"

python3 - "${EXTENSION_CSV}" <<'PY'
import csv
import sys
from pathlib import Path

rows = list(csv.DictReader(Path(sys.argv[1]).open(encoding="utf-8")))
by_name = {row["extension_name"]: row for row in rows}
for name in (
    "ducklake",
    "httpfs",
    "icu",
    "json",
    "mssql",
    "postgres_scanner",
    "sqlite_scanner",
    "tpcds",
    "tpch",
):
    row = by_name.get(name)
    if not row:
        raise SystemExit(f"{name} is missing from duckdb_extensions()")
    if row.get("installed", "").lower() != "true":
        raise SystemExit(f"{name} is not installed")
    if row.get("loaded", "").lower() != "true":
        raise SystemExit(f"{name} is not loaded")
PY

prepare_local_extension_repo() {
  local source_dir
  source_dir="$(find "${HOME}/.duckdb/extensions" -type d -path '*/v1.5.4/linux_amd64' -print -quit)"
  if [[ -z "${source_dir}" ]]; then
    echo "Installed DuckDB extension directory was not found" >&2
    return 1
  fi

  export LOCAL_EXTENSION_REPO="${RUNTIME_ROOT}/repository"
  mkdir -p "${LOCAL_EXTENSION_REPO}/v1.5.4/linux_amd64"
  cp -a "${source_dir}/." "${LOCAL_EXTENSION_REPO}/v1.5.4/linux_amd64/"

  for extension in httpfs mssql; do
    if [[ ! -f "${LOCAL_EXTENSION_REPO}/v1.5.4/linux_amd64/${extension}.duckdb_extension" ]]; then
      echo "${extension} was not copied into LOCAL_EXTENSION_REPO" >&2
      return 1
    fi
  done
}

prepare_local_extension_repo

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

  if grep -Eq '^require (ducklake|httpfs|icu|json|mssql|postgres_scanner|sqlite_scanner|tpcds|tpch): [1-9][0-9]*$' "${log_file}"; then
    echo "Required extensions were skipped by the DuckDB test runner in ${label}" >&2
    grep -E '^require (ducklake|httpfs|icu|json|mssql|postgres_scanner|sqlite_scanner|tpcds|tpch): ' "${log_file}" >&2 || true
    exit 1
  fi
}

start_ducklake_postgres() {
  docker rm -f ducklake-postgres >/dev/null 2>&1 || true
  docker run -d \
    --name ducklake-postgres \
    -e POSTGRES_USER=postgres \
    -e POSTGRES_PASSWORD=postgres \
    -e POSTGRES_DB=ducklakedb \
    -p 5432:5432 \
    postgres:15 >/dev/null
  export DUCKLAKE_POSTGRES_STARTED=1

  for _ in $(seq 1 60); do
    if docker exec ducklake-postgres pg_isready -U postgres -d ducklakedb >/dev/null 2>&1; then
      export PGHOST=127.0.0.1
      export PGPORT=5432
      export PGUSER=postgres
      export PGPASSWORD=postgres
      export PGDATABASE=ducklakedb
      export PGSSLMODE=disable
      return 0
    fi
    sleep 1
  done

  echo "DuckLake PostgreSQL service did not become ready" >&2
  return 1
}

if [[ "${TEST_NAME}" == "httpfs" ]]; then
  run_suite "sql" "${NORMAL_CONFIG}" "test/sql/*"
  run_suite "autoload" "${HTTPFS_AUTOLOAD_CONFIG}" "test/extension/*"
elif [[ "${TEST_NAME}" == "ducklake" ]]; then
  run_suite "autoload" "${DUCKLAKE_AUTOLOAD_CONFIG}" "test/sql/autoloading/autoload_data_path.test"

  python3 "${DUCKLAKE_CONFIG_HELPER}" \
    "${UPSTREAM_ROOT}/test/configs/sqlite.json" \
    "${DUCKLAKE_SQLITE_CONFIG}" \
    "test/sql/data_inlining/postgres_identifier_limit.test"
  cp "${DUCKLAKE_SQLITE_CONFIG}" "${LOG_DIR}/ducklake-sqlite.json"
  run_suite "sqlite" "${DUCKLAKE_SQLITE_CONFIG}" "${TEST_PATH}"

  python3 "${DUCKLAKE_CONFIG_HELPER}" \
    "${UPSTREAM_ROOT}/test/configs/postgres.json" \
    "${DUCKLAKE_POSTGRES_CONFIG}"
  cp "${DUCKLAKE_POSTGRES_CONFIG}" "${LOG_DIR}/ducklake-postgres.json"
  start_ducklake_postgres
  run_suite "postgres" "${DUCKLAKE_POSTGRES_CONFIG}" "${TEST_PATH}"
else
  run_suite "all" "${NORMAL_CONFIG}" "${TEST_PATH}"
fi
