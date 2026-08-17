#!/usr/bin/env bash
set -Eeuo pipefail

TEST_NAME="${1:?test name is required}"
UPSTREAM_ROOT="${2:?upstream root is required}"
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
EXTENSIONS_JSON="${BATTERY_RUNTIME_CONFIG_DIR}/extensions.json"
PROFILES_JSON="${BATTERY_RUNTIME_CONFIG_DIR}/profiles.json"
PROFILES_TSV="${BATTERY_RUNTIME_CONFIG_DIR}/profiles.tsv"
PROFILE_SKIPS_JSON="${BATTERY_RUNTIME_CONFIG_DIR}/profile-skips.json"
PROFILE_CONFIG_HELPER="${SCRIPT_DIR}/prepare-standard-profile.py"
REQUIREMENT_CHECKER="${SCRIPT_DIR}/check-test-requirements.py"
PROBE_VALIDATOR="${SCRIPT_DIR}/validate-extension-probe.py"
ICEBERG_METADATA_VERIFIER="${SCRIPT_DIR}/verify-iceberg-metadata.py"
ICEBERG_LOCAL_PREPARER="${SCRIPT_DIR}/prepare-iceberg-local-tests.sh"
DELTA_LOCAL_PREPARER="${SCRIPT_DIR}/prepare-delta-local-tests.sh"
SERVICE_MANAGER="${SCRIPT_DIR}/service-manager.sh"

mkdir -p "${RUNTIME_ROOT}/home" "${RUNTIME_ROOT}/tmp" "${RUNTIME_ROOT}/profiles" "${LOG_DIR}"
export HOME="${RUNTIME_ROOT}/home"
export TMPDIR="${RUNTIME_ROOT}/tmp"
export PATH="$(cd "$(dirname "${DUCKDB_BIN}")" && pwd):${PATH}"

# shellcheck disable=SC1091
source "${SERVICE_MANAGER}"
cleanup_test_runtime() {
  local status=$?
  trap - EXIT
  qa_service_stop_all || true
  if [[ "${TEST_NAME}" == "iceberg" && -f "${ICEBERG_LOCAL_PREPARER}" ]]; then
    bash "${ICEBERG_LOCAL_PREPARER}" stop \
      "${UPSTREAM_ROOT}" "${RUNTIME_ROOT}" "${LOG_DIR}" || true
  fi
  exit "${status}"
}
trap cleanup_test_runtime EXIT

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
  "${PROBE_VALIDATOR}" \
  "${ICEBERG_METADATA_VERIFIER}" \
  "${ICEBERG_LOCAL_PREPARER}" \
  "${DELTA_LOCAL_PREPARER}" \
  "${SERVICE_MANAGER}"; do
  if [[ ! -e "${required}" ]]; then
    echo "Required test runtime input is missing: ${required}" >&2
    exit 1
  fi
done

# DuckDB's upstream Iceberg CI links the extension into the unittest binary, so
# its log type is registered before SQLLogicTests call enable_logging('Iceberg').
# Our shared runtime installs dynamic extensions instead. Explicitly load Iceberg
# in this battery's generated profile scripts to reproduce the upstream startup
# contract; the two pre-load negative tests remain explicitly replaced by the
# metadata smoke verifier.
if [[ "${TEST_NAME}" == "iceberg" ]]; then
  for profile_init in "${BATTERY_RUNTIME_CONFIG_DIR}"/init-profile-*.sql; do
    if ! grep -Eqi '^[[:space:]]*LOAD[[:space:]]+iceberg[[:space:]]*;' "${profile_init}"; then
      printf '\nLOAD iceberg;\n' >>"${profile_init}"
    fi
  done
fi

EXTENSION_CSV="${LOG_DIR}/extensions.csv"

sql_from_file() {
  sed '/^[[:space:]]*--/d; /^[[:space:]]*$/d' "$1" | tr '\n' ' '
}

INSTALL_SQL="$(sql_from_file "${INSTALL_SCRIPT}")"
INIT_SQL="$(sql_from_file "${INIT_SCRIPT}")"

cp "${BATTERY_RUNTIME_CONFIG_DIR}/battery.json" "${LOG_DIR}/battery.json"
cp "${EXTENSIONS_JSON}" "${LOG_DIR}/extensions.json"
cp "${BATTERY_RUNTIME_CONFIG_DIR}/services.json" "${LOG_DIR}/services.json"
cp "${BATTERY_RUNTIME_CONFIG_DIR}/prerequisites.json" "${LOG_DIR}/prerequisites.json"
cp "${BATTERY_RUNTIME_CONFIG_DIR}/capabilities.json" "${LOG_DIR}/capabilities.json"
cp "${PROFILES_JSON}" "${LOG_DIR}/profiles.json"
cp "${INSTALL_SCRIPT}" "${LOG_DIR}/install-extensions.sql"
cp "${INIT_SCRIPT}" "${LOG_DIR}/init-extensions.sql"
for init_profile in "${BATTERY_RUNTIME_CONFIG_DIR}"/init-profile-*.sql; do
  cp "${init_profile}" "${LOG_DIR}/$(basename "${init_profile}")"
done

{
  echo "test_name=${TEST_NAME}"
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

if [[ "${TEST_NAME}" == "delta" ]]; then
  DELTA_ENV_FILE="${RUNTIME_ROOT}/delta-local.env"
  bash "${DELTA_LOCAL_PREPARER}" "${UPSTREAM_ROOT}" "${RUNTIME_ROOT}" "${LOG_DIR}"
  if [[ ! -f "${DELTA_ENV_FILE}" ]]; then
    echo "Delta local environment was not generated: ${DELTA_ENV_FILE}" >&2
    exit 1
  fi
  # shellcheck disable=SC1090
  source "${DELTA_ENV_FILE}"
  cat "${LOG_DIR}/delta-local-contract.txt" >>"${LOG_DIR}/test-info.txt"
fi

if [[ "${TEST_NAME}" == "iceberg" ]]; then
  ICEBERG_ENV_FILE="${RUNTIME_ROOT}/iceberg-local.env"
  bash "${ICEBERG_LOCAL_PREPARER}" start \
    "${UPSTREAM_ROOT}" "${RUNTIME_ROOT}" "${LOG_DIR}"
  if [[ ! -f "${ICEBERG_ENV_FILE}" ]]; then
    echo "Iceberg local environment was not generated: ${ICEBERG_ENV_FILE}" >&2
    exit 1
  fi
  # shellcheck disable=SC1090
  source "${ICEBERG_ENV_FILE}"
  cat "${LOG_DIR}/iceberg-local-contract.txt" >>"${LOG_DIR}/test-info.txt"
fi

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

iceberg_local_filter() {
  local test_file
  local relative_path
  local joined=""
  local -a test_files=()

  mapfile -d '' test_files < <(
    {
      find "${UPSTREAM_ROOT}/test/sql/local" -type f \
        \( -name '*.test' -o -name '*.test_slow' -o -name '*.test_coverage' \) \
        ! -path '*/catalog_test_config_setup/*' \
        ! -path '*/catalog_custom_setup/*' \
        -print0
      find "${UPSTREAM_ROOT}/test/sql/local/catalog_custom_setup/fixture" -type f \
        \( -name '*.test' -o -name '*.test_slow' -o -name '*.test_coverage' \) \
        -print0
    } | sort -z
  )
  if [[ "${#test_files[@]}" -eq 0 ]]; then
    echo "No Iceberg local SQLLogicTest files were found" >&2
    return 1
  fi
  for test_file in "${test_files[@]}"; do
    relative_path="${test_file#"${UPSTREAM_ROOT}/"}"
    if [[ -n "${joined}" ]]; then
      joined+=,
    fi
    joined+="${relative_path}"
  done
  printf '%s\n' "${joined}"
}

prepare_iceberg_fixture_config() {
  local base_profile_name=$1
  local destination=$2
  local temporary_profiles="${RUNTIME_ROOT}/profiles/iceberg-fixture-profiles.json"

  python3 - \
    "${PROFILES_JSON}" "${base_profile_name}" "${temporary_profiles}" <<'PY'
import json
import sys
from pathlib import Path

profiles_path = Path(sys.argv[1])
profile_name = sys.argv[2]
destination = Path(sys.argv[3])
profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
profile = next(item for item in profiles if item["name"] == profile_name)
fixture = dict(profile)
fixture["name"] = "fixture-catalog"
fixture["testConfig"] = {"kind": "upstream", "path": "test/configs/fixture.json"}
destination.write_text(json.dumps([fixture], indent=2) + "\n", encoding="utf-8")
PY

  python3 "${PROFILE_CONFIG_HELPER}" \
    "${temporary_profiles}" \
    fixture-catalog \
    "${UPSTREAM_ROOT}" \
    "${destination}" \
    "${EXTENSIONS_JSON}" \
    "${PROFILE_SKIPS_JSON}" \
    "${BATTERY_RUNTIME_CONFIG_DIR}"
}

reset_ducklake_postgres_database() {
  command -v psql >/dev/null 2>&1 || {
    echo "psql is required for DuckLake PostgreSQL test isolation" >&2
    return 1
  }
  if [[ "${PGDATABASE:-}" != "ducklakedb" ]]; then
    echo "Unexpected DuckLake PostgreSQL database: ${PGDATABASE:-<unset>}" >&2
    return 1
  fi

  # The official PostgreSQL image briefly starts a temporary server while it
  # creates POSTGRES_DB, then stops it and launches the final server. pg_isready
  # can report success during that transition, so retry the complete reset until
  # one transaction reaches the final server successfully.
  local attempt
  for attempt in $(seq 1 60); do
    if PGDATABASE=postgres psql --no-psqlrc --set=ON_ERROR_STOP=1 --quiet <<'SQL'
DROP DATABASE IF EXISTS ducklakedb WITH (FORCE);
CREATE DATABASE ducklakedb OWNER postgres;
\connect ducklakedb
CREATE SCHEMA main AUTHORIZATION postgres;
SQL
    then
      return 0
    fi
    sleep 1
  done

  echo "PostgreSQL did not become stable enough to recreate ducklakedb" >&2
  return 1
}

run_ducklake_postgres_isolated() {
  local label=$1
  local config=$2
  local log_file="${LOG_DIR}/unittest-${label}.log"
  local test_file
  local relative_path
  local status
  local index=0
  local total
  local -a test_files=()

  mapfile -d '' test_files < <(
    find "${UPSTREAM_ROOT}/test/sql" -type f \
      \( -name '*.test' -o -name '*.test_slow' -o -name '*.test_coverage' \) \
      -print0 | sort -z
  )
  total=${#test_files[@]}
  if [[ "${total}" -eq 0 ]]; then
    echo "No DuckLake PostgreSQL SQLLogicTest files were found" >&2
    return 1
  fi

  : >"${log_file}"
  printf 'Running %s DuckLake PostgreSQL files with process and database isolation\n' "${total}" \
    | tee -a "${log_file}"

  for test_file in "${test_files[@]}"; do
    relative_path="${test_file#"${UPSTREAM_ROOT}/"}"
    index=$((index + 1))
    printf '[%s/%s] %s\n' "${index}" "${total}" "${relative_path}" \
      | tee -a "${log_file}"

    reset_ducklake_postgres_database >>"${log_file}" 2>&1 || {
      echo "Unable to recreate DuckLake PostgreSQL database before ${relative_path}" \
        | tee -a "${log_file}" >&2
      return 1
    }

    status=0
    "${UNITTEST_BIN}" \
      --test-config "${config}" \
      --test-dir "${UPSTREAM_ROOT}" \
      "${relative_path}" \
      2>&1 | tee -a "${log_file}" || status=$?

    if [[ "${status}" -ne 0 ]]; then
      echo "DuckLake PostgreSQL isolated test failed: ${relative_path}" \
        | tee -a "${log_file}" >&2
      return "${status}"
    fi
  done

  python3 "${REQUIREMENT_CHECKER}" "${log_file}" "${EXTENSIONS_JSON}"
}

run_case_specific_verification() {
  local profile_name=$1
  if [[ "${TEST_NAME}" == "iceberg" && "${profile_name}" == "all" ]]; then
    python3 "${ICEBERG_METADATA_VERIFIER}" "${DUCKDB_BIN}" "${UPSTREAM_ROOT}" \
      2>&1 | tee "${LOG_DIR}/iceberg-metadata-smoke.log"
  fi
}

# Materialize the complete profile plan before launching any profile. Commands
# inside a profile may inherit stdin; they must never be able to consume the
# remaining profile definitions. This keeps profile isolation compatible with
# runners that bridge Linux orchestration to native Windows processes.
mapfile -t profile_rows <"${PROFILES_TSV}"
echo "[qa-profiles] manifest=${PROFILES_TSV} count=${#profile_rows[@]}" >&2

for profile_row in "${profile_rows[@]}"; do
  IFS=$'\t' read -r profile_name test_filter <<<"${profile_row}"
  [[ -n "${profile_name}" ]] || continue
  echo "[qa-profiles] start name=${profile_name} filter=${test_filter}" >&2

  # Profile services may export credentials, endpoints and provider-specific
  # variables. Run each profile in its own subshell so those mutations disappear
  # before the next profile starts. This keeps local emulators and real cloud
  # profiles independent without maintaining a service-specific reset list.
  (
    profile_config="${RUNTIME_ROOT}/profiles/${profile_name}.json"
    profile_services="${BATTERY_RUNTIME_CONFIG_DIR}/profile-services-${profile_name}.json"
    python3 "${PROFILE_CONFIG_HELPER}" \
      "${PROFILES_JSON}" \
      "${profile_name}" \
      "${UPSTREAM_ROOT}" \
      "${profile_config}" \
      "${EXTENSIONS_JSON}" \
      "${PROFILE_SKIPS_JSON}" \
      "${BATTERY_RUNTIME_CONFIG_DIR}"
    cp "${profile_config}" "${LOG_DIR}/profile-${profile_name}.json"
    cp "${profile_services}" "${LOG_DIR}/profile-services-${profile_name}.json"

    qa_service_manager_init \
      "${RUNTIME_ROOT}/profile-services/${profile_name}" \
      "${UPSTREAM_ROOT}" \
      "${LOG_DIR}/services/${profile_name}"
    trap 'qa_service_stop_all' EXIT
    if [[ "${TEST_NAME}" == "delta" && -n "${DELTA_MINIO_CONTAINER:-}" ]]; then
      QA_SERVICE_CLEANUPS+=("container|delta-minio|${DELTA_MINIO_CONTAINER}")
    fi
    qa_service_start_file "${profile_services}"

    status=0
    if [[ "${TEST_NAME}" == "ducklake" && "${profile_name}" == "postgres" ]]; then
      run_ducklake_postgres_isolated "${profile_name}" "${profile_config}" || status=$?
    elif [[ "${TEST_NAME}" == "iceberg" && "${profile_name}" == "all" ]]; then
      local_filter="$(iceberg_local_filter)"
      run_suite "${profile_name}-local" "${profile_config}" "${local_filter}" || status=$?
      if [[ "${status}" -eq 0 ]]; then
        fixture_config="${RUNTIME_ROOT}/profiles/${profile_name}-fixture-catalog.json"
        prepare_iceberg_fixture_config "${profile_name}" "${fixture_config}" || status=$?
        if [[ "${status}" -eq 0 ]]; then
          cp "${fixture_config}" "${LOG_DIR}/profile-${profile_name}-fixture-catalog.json"
          run_suite "${profile_name}-fixture-catalog" "${fixture_config}" \
            "test/sql/local/catalog_test_config_setup/*" || status=$?
        fi
      fi
    else
      run_suite "${profile_name}" "${profile_config}" "${test_filter}" || status=$?
    fi
    if [[ "${status}" -eq 0 ]]; then
      run_case_specific_verification "${profile_name}" || status=$?
    fi

    qa_service_stop_all
    trap - EXIT
    exit "${status}"
  ) || exit $?

  echo "[qa-profiles] ready name=${profile_name}" >&2
done
