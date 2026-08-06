#!/usr/bin/env bash
set -Eeuo pipefail

BATTERY_CONFIG_FILE="${1:?resolved battery JSON is required}"
UPSTREAM_ROOT="${2:?upstream root is required}"
ARTIFACT_DIR="${ARTIFACT_DIR:-build/artifact}"
STARTED_AT_MS="${RESULT_STARTED_AT_MS:-$(date +%s%3N)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREPARE_SCRIPT="${SCRIPT_DIR}/prepare-test-battery.py"
SERVICE_MANAGER="${SCRIPT_DIR}/service-manager.sh"
RESULT_WRITER="${SCRIPT_DIR}/write-test-result.py"
BATTERY_NAME_HINT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["name"])' "${BATTERY_CONFIG_FILE}")"
BATTERY_RUNTIME_CONFIG_DIR="${RUNNER_TEMP:-${PWD}/build/runtime}/battery-config/${BATTERY_NAME_HINT}"
DUCKDB_BIN="${ARTIFACT_DIR}/bin/duckdb"
UNITTEST_BIN="${ARTIFACT_DIR}/bin/unittest"

rm -rf "${BATTERY_RUNTIME_CONFIG_DIR}"
python3 "${PREPARE_SCRIPT}" "${BATTERY_CONFIG_FILE}" "${BATTERY_RUNTIME_CONFIG_DIR}"
# shellcheck disable=SC1091
source "${BATTERY_RUNTIME_CONFIG_DIR}/battery.env"
# shellcheck disable=SC1091
source "${SERVICE_MANAGER}"

# The upstream BigQuery suite uses the same project as its billing project in
# this repository. Keep the explicit variable available to SQLLogicTest even
# when the workflow only passes BQ_TEST_PROJECT to the process environment.
if [[ "${BATTERY_NAME}" == "bigquery" && -n "${BQ_TEST_PROJECT:-}" ]]; then
  export BQ_TEST_BILLING_PROJECT="${BQ_TEST_BILLING_PROJECT:-${BQ_TEST_PROJECT}}"
fi

LOG_DIR="${PWD}/build/logs/${BATTERY_NAME}"
RESULT_DIR="${PWD}/build/results/${BATTERY_NAME}"
RESULT_FILE="${RESULT_DIR}/result.json"
IGNORED_TEST_ROOT="${RUNNER_TEMP:-${PWD}/build/runtime}/ignored-tests/${BATTERY_NAME}"
RUNTIME_ROOT="${RUNNER_TEMP:-${PWD}/build/runtime}/${BATTERY_NAME}"
SERVICE_RUNTIME_ROOT="${RUNTIME_ROOT}/services"
mkdir -p "${RUNTIME_ROOT}/home" "${RUNTIME_ROOT}/tmp" "${LOG_DIR}" "${RESULT_DIR}" "${IGNORED_TEST_ROOT}" "${LOG_DIR}/services"
export HOME="${RUNTIME_ROOT}/home"
export TMPDIR="${RUNTIME_ROOT}/tmp"

finalize_result() {
  local original_status=$?
  local writer_status=0
  trap - EXIT
  qa_service_stop_all || true
  python3 "${RESULT_WRITER}" \
    --battery-config "${BATTERY_CONFIG_FILE}" \
    --log-dir "${LOG_DIR}" \
    --output "${RESULT_FILE}" \
    --exit-code "${original_status}" \
    --started-at-ms "${STARTED_AT_MS}" || writer_status=$?
  if [[ "${original_status}" -eq 0 && "${writer_status}" -ne 0 ]]; then
    original_status="${writer_status}"
  fi
  exit "${original_status}"
}
trap finalize_result EXIT

# Services may invoke DuckDB while preparing their fixtures. Make the packaged
# runtime available before prerequisite checks and before any service starts,
# rather than relying on a later runner-specific PATH modification.
if [[ ! -x "${DUCKDB_BIN}" ]]; then
  echo "DuckDB runtime is missing or not executable: ${DUCKDB_BIN}" >&2
  exit 1
fi
if [[ ! -x "${UNITTEST_BIN}" ]]; then
  echo "DuckDB unittest runtime is missing or not executable: ${UNITTEST_BIN}" >&2
  exit 1
fi
if [[ ! -x "${RESULT_WRITER}" ]]; then
  echo "Structured result writer is missing or not executable: ${RESULT_WRITER}" >&2
  exit 1
fi
export PATH="$(cd "$(dirname "${DUCKDB_BIN}")" && pwd):${PATH}"

# DuckDB's SQLLogicTest `require` directive is enabled through the unittest
# command-line option, not through the test configuration file. The upstream
# BigQuery suite marks every file with `require bigquery`, so wrap the job-local
# unittest executable and provide that option only for this battery.
if [[ "${BATTERY_NAME}" == "bigquery" ]]; then
  mv "${UNITTEST_BIN}" "${UNITTEST_BIN}.real"
  cat >"${UNITTEST_BIN}" <<'WRAPPER'
#!/usr/bin/env bash
set -Eeuo pipefail
binary_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${binary_dir}/unittest.real" --require bigquery "$@"
WRAPPER
  chmod +x "${UNITTEST_BIN}"
fi

ignore_upstream_test() {
  local relative_path=$1
  local reason=$2
  local source_path="${UPSTREAM_ROOT}/${relative_path}"
  local target_path="${IGNORED_TEST_ROOT}/${relative_path}"

  if [[ ! -f "${source_path}" ]]; then
    echo "Configured ignored test is missing: ${relative_path}" >&2
    exit 1
  fi

  mkdir -p "$(dirname "${target_path}")"
  mv "${source_path}" "${target_path}"
  printf '%s\t%s\n' "${relative_path}" "${reason}" >>"${LOG_DIR}/ignored-tests.tsv"
}

while IFS=$'\t' read -r relative_path reason; do
  if [[ -n "${relative_path}" ]]; then
    ignore_upstream_test "${relative_path}" "${reason}"
  fi
done <"${BATTERY_RUNTIME_CONFIG_DIR}/ignored-global.tsv"

if [[ "${UPSTREAM_REF}" =~ ^[0-9a-fA-F]{40}$ ]]; then
  actual_commit="$(git -C "${UPSTREAM_ROOT}" rev-parse HEAD)"
  if [[ "${actual_commit,,}" != "${UPSTREAM_REF,,}" ]]; then
    echo "${BATTERY_NAME} checkout must be ${UPSTREAM_REF}; found ${actual_commit}" >&2
    exit 1
  fi
fi

export ARTIFACT_DIR
export BATTERY_RUNTIME_CONFIG_DIR
export DUCKDB_VERSION
export MSSQL_RELEASE_TAG="${UPSTREAM_REF}"

qa_prerequisite_check_file "${BATTERY_RUNTIME_CONFIG_DIR}/prerequisites.json"
qa_service_manager_init "${SERVICE_RUNTIME_ROOT}" "${UPSTREAM_ROOT}" "${LOG_DIR}/services"
qa_service_start_file "${BATTERY_RUNTIME_CONFIG_DIR}/services.json"

status=0
case "${RUNNER_KIND}" in
  standard)
    bash "${SCRIPT_DIR}/run-standard-tests.sh" \
      "${BATTERY_NAME}" \
      "${UPSTREAM_ROOT}" || status=$?
    ;;
  postgres-scanner)
    bash "${SCRIPT_DIR}/run-postgres-scanner-tests.sh" \
      "${UPSTREAM_ROOT}" \
      "${TEST_FILTER}" \
      "${UPSTREAM_REF}" || status=$?
    ;;
  mssql-release)
    bash "${SCRIPT_DIR}/run-mssql-configured-tests.sh" \
      "${UPSTREAM_ROOT}" \
      "${TEST_FILTER}" || status=$?
    ;;
  *)
    echo "Unsupported test battery runner: ${RUNNER_KIND}" >&2
    status=2
    ;;
esac

exit "${status}"
