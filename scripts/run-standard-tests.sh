#!/usr/bin/env bash
set -Eeuo pipefail

TEST_NAME="${1:?test name is required}"
UPSTREAM_ROOT="${2:?upstream root is required}"
ARTIFACT_DIR="${ARTIFACT_DIR:-build/artifact}"
BATTERY_RUNTIME_CONFIG_DIR="${BATTERY_RUNTIME_CONFIG_DIR:?battery runtime config directory is required}"
DUCKDB_VERSION="${DUCKDB_VERSION:?DuckDB version is required}"
SETUP_KIND="${SETUP_KIND:?setup kind is required}"

DUCKDB_BIN="${ARTIFACT_DIR}/bin/duckdb"
UNITTEST_BIN="${ARTIFACT_DIR}/bin/unittest"
RUNTIME_ROOT="${RUNNER_TEMP:-${PWD}/build/runtime}/${TEST_NAME}"
LOG_DIR="${PWD}/build/logs/${TEST_NAME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_SCRIPT="${BATTERY_RUNTIME_CONFIG_DIR}/install-extensions.sql"
INIT_SCRIPT="${BATTERY_RUNTIME_CONFIG_DIR}/init-extensions.sql"
EXTENSIONS_JSON="${BATTERY_RUNTIME_CONFIG_DIR}/extensions.json"
PROFILES_JSON="${BATTERY_RUNTIME_CONFIG_DIR}/profiles.json"
PROFILES_TSV="${BATTERY_RUNTIME_CONFIG_DIR}/profiles.tsv"
PROFILE_SKIPS_JSON="${BATTERY_RUNTIME_CONFIG_DIR}/profile-skips.json"
PROFILE_CONFIG_HELPER="${SCRIPT_DIR}/prepare-standard-profile.py"
REQUIREMENT_CHECKER="${SCRIPT_DIR}/check-test-requirements.py"
PROBE_VALIDATOR="${SCRIPT_DIR}/validate-extension-probe.py"

mkdir -p "${RUNTIME_ROOT}/home" "${RUNTIME_ROOT}/tmp" "${RUNTIME_ROOT}/profiles" "${LOG_DIR}"
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
  "${PROFILES_JSON}" \
  "${PROFILES_TSV}" \
  "${PROFILE_SKIPS_JSON}" \
  "${PROFILE_CONFIG_HELPER}" \
  "${REQUIREMENT_CHECKER}" \
  "${PROBE_VALIDATOR}"; do
  if [[ ! -e "${required}" ]]; then
    echo "Required test runtime input is missing: ${required}" >&2
    exit 1
  fi
done

case "${SETUP_KIND}" in
  none|ducklake-catalogs)
    ;;
  httpfs-services)
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/setup-httpfs.sh" "${RUNTIME_ROOT}" "${UPSTREAM_ROOT}"
    ;;
  bigquery-gcp)
    for variable_name in GOOGLE_APPLICATION_CREDENTIALS BQ_TEST_PROJECT BQ_TEST_DATASET; do
      if [[ -z "${!variable_name:-}" ]]; then
        echo "BigQuery setup requires ${variable_name}" >&2
        exit 1
      fi
    done
    ;;
  *)
    echo "Unsupported standard-runner setup: ${SETUP_KIND}" >&2
    exit 2
    ;;
esac

EXTENSION_CSV="${LOG_DIR}/extensions.csv"

sql_from_file() {
  sed '/^[[:space:]]*--/d; /^[[:space:]]*$/d' "$1" | tr '\n' ' '
}

INSTALL_SQL="$(sql_from_file "${INSTALL_SCRIPT}")"
INIT_SQL="$(sql_from_file "${INIT_SCRIPT}")"

cp "${BATTERY_RUNTIME_CONFIG_DIR}/battery.json" "${LOG_DIR}/battery.json"
cp "${EXTENSIONS_JSON}" "${LOG_DIR}/extensions.json"
cp "${PROFILES_JSON}" "${LOG_DIR}/profiles.json"
cp "${INSTALL_SCRIPT}" "${LOG_DIR}/install-extensions.sql"
cp "${INIT_SCRIPT}" "${LOG_DIR}/init-extensions.sql"
for init_profile in "${BATTERY_RUNTIME_CONFIG_DIR}"/init-profile-*.sql; do
  cp "${init_profile}" "${LOG_DIR}/$(basename "${init_profile}")"
done

{
  echo "test_name=${TEST_NAME}"
  echo "setup_kind=${SETUP_KIND}"
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
  if [[ "${DUCKLAKE_POSTGRES_STARTED:-0}" == "1" ]]; then
    return 0
  fi
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

while IFS=$'\t' read -r profile_name test_filter runtime_setup; do
  [[ -n "${profile_name}" ]] || continue
  profile_config="${RUNTIME_ROOT}/profiles/${profile_name}.json"
  python3 "${PROFILE_CONFIG_HELPER}" \
    "${PROFILES_JSON}" \
    "${profile_name}" \
    "${UPSTREAM_ROOT}" \
    "${profile_config}" \
    "${EXTENSIONS_JSON}" \
    "${PROFILE_SKIPS_JSON}" \
    "${BATTERY_RUNTIME_CONFIG_DIR}"
  cp "${profile_config}" "${LOG_DIR}/profile-${profile_name}.json"

  case "${runtime_setup}" in
    none)
      ;;
    ducklake-postgres-15)
      start_ducklake_postgres
      ;;
    *)
      echo "Unsupported profile runtime setup: ${runtime_setup}" >&2
      exit 2
      ;;
  esac

  run_suite "${profile_name}" "${profile_config}" "${test_filter}"
done <"${PROFILES_TSV}"
