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
SERVICE_MANAGER="${SCRIPT_DIR}/service-manager.sh"

mkdir -p "${RUNTIME_ROOT}/home" "${RUNTIME_ROOT}/tmp" "${RUNTIME_ROOT}/profiles" "${LOG_DIR}"
export HOME="${RUNTIME_ROOT}/home"
export TMPDIR="${RUNTIME_ROOT}/tmp"
export PATH="$(cd "$(dirname "${DUCKDB_BIN}")" && pwd):${PATH}"

# shellcheck disable=SC1091
source "${SERVICE_MANAGER}"
trap qa_service_stop_all EXIT

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
  "${SERVICE_MANAGER}"; do
  if [[ ! -e "${required}" ]]; then
    echo "Required test runtime input is missing: ${required}" >&2
    exit 1
  fi
done

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

while IFS=$'\t' read -r profile_name test_filter; do
  [[ -n "${profile_name}" ]] || continue
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
  qa_service_start_file "${profile_services}"

  status=0
  run_suite "${profile_name}" "${profile_config}" "${test_filter}" || status=$?
  qa_service_stop_all
  if [[ "${status}" -ne 0 ]]; then
    exit "${status}"
  fi
done <"${PROFILES_TSV}"
