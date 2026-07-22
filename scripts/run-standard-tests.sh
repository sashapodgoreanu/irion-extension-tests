#!/usr/bin/env bash
set -Eeuo pipefail

TEST_NAME="${1:?test name is required}"
UPSTREAM_ROOT="${2:?upstream root is required}"
TEST_PATH="${3:?test path is required}"
ARTIFACT_DIR="${ARTIFACT_DIR:-build/artifact}"
BATTERY_RUNTIME_CONFIG_DIR="${BATTERY_RUNTIME_CONFIG_DIR:?battery runtime config directory is required}"
DUCKDB_VERSION="${DUCKDB_VERSION:?DuckDB version is required}"

DUCKDB_BIN="${ARTIFACT_DIR}/bin/duckdb"
UNITTEST_BIN="${ARTIFACT_DIR}/bin/unittest"
RUNTIME_ROOT="${RUNNER_TEMP:-${PWD}/build/runtime}/${TEST_NAME}"
LOG_DIR="${PWD}/build/logs/${TEST_NAME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_SCRIPT="${BATTERY_RUNTIME_CONFIG_DIR}/install-extensions.sql"
INIT_SCRIPT="${BATTERY_RUNTIME_CONFIG_DIR}/init-extensions.sql"
DUCKLAKE_AUTOLOAD_INIT_SCRIPT="${BATTERY_RUNTIME_CONFIG_DIR}/init-ducklake-autoload.sql"
HTTPFS_AUTOLOAD_INIT_SCRIPT="${BATTERY_RUNTIME_CONFIG_DIR}/init-without-httpfs.sql"
EXTENSIONS_JSON="${BATTERY_RUNTIME_CONFIG_DIR}/extensions.json"
PROFILE_SKIPS_JSON="${BATTERY_RUNTIME_CONFIG_DIR}/profile-skips.json"
DUCKLAKE_CONFIG_HELPER="${SCRIPT_DIR}/prepare-ducklake-config.py"
REQUIREMENT_CHECKER="${SCRIPT_DIR}/check-test-requirements.py"
PROBE_VALIDATOR="${SCRIPT_DIR}/validate-extension-probe.py"

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

for required in \
  "${DUCKDB_BIN}" \
  "${UNITTEST_BIN}" \
  "${INSTALL_SCRIPT}" \
  "${INIT_SCRIPT}" \
  "${EXTENSIONS_JSON}" \
  "${PROFILE_SKIPS_JSON}" \
  "${DUCKLAKE_CONFIG_HELPER}" \
  "${REQUIREMENT_CHECKER}" \
  "${PROBE_VALIDATOR}"; do
  if [[ ! -e "${required}" ]]; then
    echo "Required test runtime input is missing: ${required}" >&2
    exit 1
  fi
done

if [[ "${TEST_NAME}" == "httpfs" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/setup-httpfs.sh" "${RUNTIME_ROOT}" "${UPSTREAM_ROOT}"
fi

EXTENSION_CSV="${LOG_DIR}/extensions.csv"
NORMAL_CONFIG="${RUNTIME_ROOT}/all-extensions.json"
HTTPFS_AUTOLOAD_CONFIG="${RUNTIME_ROOT}/httpfs-autoload.json"
DUCKLAKE_AUTOLOAD_CONFIG="${RUNTIME_ROOT}/ducklake-autoload.json"
DUCKLAKE_SQLITE_CONFIG="${RUNTIME_ROOT}/ducklake-sqlite.json"
DUCKLAKE_POSTGRES_CONFIG="${RUNTIME_ROOT}/ducklake-postgres.json"

sql_from_file() {
  sed '/^[[:space:]]*--/d; /^[[:space:]]*$/d' "$1" | tr '\n' ' '
}

INSTALL_SQL="$(sql_from_file "${INSTALL_SCRIPT}")"
INIT_SQL="$(sql_from_file "${INIT_SCRIPT}")"
HTTPFS_AUTOLOAD_CONNECTION_SQL="$(sql_from_file "${HTTPFS_AUTOLOAD_INIT_SCRIPT}")"
DUCKLAKE_AUTOLOAD_CONNECTION_SQL="$(sql_from_file "${DUCKLAKE_AUTOLOAD_INIT_SCRIPT}")"

cat >"${NORMAL_CONFIG}" <<EOF
{
  "description": "${TEST_NAME} compatibility battery from config/extensions.yml",
  "autoloading": "all",
  "init_script": "${INIT_SCRIPT}",
  "on_new_connection": "${INIT_SQL}",
  "statically_loaded_extensions": ["core_functions", "parquet"],
  "summarize_failures": true
}
EOF

cat >"${HTTPFS_AUTOLOAD_CONFIG}" <<EOF
{
  "description": "HTTPFS autoloading profile with configured compatibility extensions",
  "autoloading": "all",
  "init_script": "${HTTPFS_AUTOLOAD_INIT_SCRIPT}",
  "on_new_connection": "${HTTPFS_AUTOLOAD_CONNECTION_SQL}",
  "statically_loaded_extensions": ["core_functions"],
  "summarize_failures": true
}
EOF

cat >"${DUCKLAKE_AUTOLOAD_CONFIG}" <<EOF
{
  "description": "DuckLake filesystem autoloading profile with HTTPFS initially unloaded",
  "autoloading": "all",
  "init_script": "${DUCKLAKE_AUTOLOAD_INIT_SCRIPT}",
  "on_new_connection": "${DUCKLAKE_AUTOLOAD_CONNECTION_SQL}",
  "statically_loaded_extensions": ["core_functions", "parquet"],
  "summarize_failures": true
}
EOF

cp "${BATTERY_RUNTIME_CONFIG_DIR}/battery.json" "${LOG_DIR}/battery.json"
cp "${EXTENSIONS_JSON}" "${LOG_DIR}/extensions.json"
cp "${INSTALL_SCRIPT}" "${LOG_DIR}/install-extensions.sql"
cp "${INIT_SCRIPT}" "${LOG_DIR}/init-extensions.sql"
cp "${HTTPFS_AUTOLOAD_INIT_SCRIPT}" "${LOG_DIR}/init-without-httpfs.sql"
cp "${DUCKLAKE_AUTOLOAD_INIT_SCRIPT}" "${LOG_DIR}/init-ducklake-autoload.sql"
cp "${NORMAL_CONFIG}" "${LOG_DIR}/all-extensions.json"
cp "${HTTPFS_AUTOLOAD_CONFIG}" "${LOG_DIR}/httpfs-autoload.json"
cp "${DUCKLAKE_AUTOLOAD_CONFIG}" "${LOG_DIR}/ducklake-autoload.json"

{
  echo "test_name=${TEST_NAME}"
  echo "test_path=${TEST_PATH}"
  echo "duckdb_version=${DUCKDB_VERSION}"
  echo "upstream_commit=$(git -C "${UPSTREAM_ROOT}" rev-parse HEAD)"
} >"${LOG_DIR}/test-info.txt"

"${DUCKDB_BIN}" -csv -header -c "${INSTALL_SQL} ${INIT_SQL}
  SELECT extension_name, installed, loaded, extension_version, install_mode, installed_from
  FROM duckdb_extensions()
  ORDER BY extension_name;" | tee "${EXTENSION_CSV}"

python3 "${PROBE_VALIDATOR}" "${EXTENSION_CSV}" "${EXTENSIONS_JSON}"

prepare_local_extension_repo() {
  local source_dir="${HOME}/.duckdb/extensions/${DUCKDB_VERSION}/linux_amd64"
  if [[ ! -d "${source_dir}" ]]; then
    echo "Installed DuckDB extension directory was not found: ${source_dir}" >&2
    return 1
  fi

  export LOCAL_EXTENSION_REPO="${RUNTIME_ROOT}/repository"
  mkdir -p "${LOCAL_EXTENSION_REPO}/${DUCKDB_VERSION}/linux_amd64"
  cp -a "${source_dir}/." "${LOCAL_EXTENSION_REPO}/${DUCKDB_VERSION}/linux_amd64/"
  echo "local_extension_repo=${LOCAL_EXTENSION_REPO}" >>"${LOG_DIR}/test-info.txt"
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

  python3 "${REQUIREMENT_CHECKER}" "${log_file}" "${EXTENSIONS_JSON}"
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
  run_suite "sql" "${NORMAL_CONFIG}" "${TEST_PATH}"
  run_suite "autoload" "${HTTPFS_AUTOLOAD_CONFIG}" "test/extension/*"
elif [[ "${TEST_NAME}" == "ducklake" ]]; then
  run_suite "autoload" "${DUCKLAKE_AUTOLOAD_CONFIG}" "test/sql/autoloading/autoload_data_path.test"

  python3 "${DUCKLAKE_CONFIG_HELPER}" \
    "${UPSTREAM_ROOT}/test/configs/sqlite.json" \
    "${DUCKLAKE_SQLITE_CONFIG}" \
    "${EXTENSIONS_JSON}" \
    "${PROFILE_SKIPS_JSON}" \
    sqlite \
    "${INIT_SCRIPT}"
  cp "${DUCKLAKE_SQLITE_CONFIG}" "${LOG_DIR}/ducklake-sqlite.json"
  run_suite "sqlite" "${DUCKLAKE_SQLITE_CONFIG}" "${TEST_PATH}"

  python3 "${DUCKLAKE_CONFIG_HELPER}" \
    "${UPSTREAM_ROOT}/test/configs/postgres.json" \
    "${DUCKLAKE_POSTGRES_CONFIG}" \
    "${EXTENSIONS_JSON}" \
    "${PROFILE_SKIPS_JSON}" \
    postgres \
    "${INIT_SCRIPT}"
  cp "${DUCKLAKE_POSTGRES_CONFIG}" "${LOG_DIR}/ducklake-postgres.json"
  start_ducklake_postgres
  run_suite "postgres" "${DUCKLAKE_POSTGRES_CONFIG}" "${TEST_PATH}"
else
  run_suite "all" "${NORMAL_CONFIG}" "${TEST_PATH}"
fi
