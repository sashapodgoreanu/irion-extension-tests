#!/usr/bin/env bash
set -Eeuo pipefail

BATTERY_CONFIG_FILE="${1:?resolved battery JSON is required}"
UPSTREAM_ROOT="${2:?upstream root is required}"
ARTIFACT_DIR="${ARTIFACT_DIR:-build/artifact}"
STARTED_AT_MS="${RESULT_STARTED_AT_MS:-$(date +%s%3N)}"
QA_SERVICE_HOST_ONLY="${QA_SERVICE_HOST_ONLY:-0}"
QA_SERVICE_PROFILE="${QA_SERVICE_PROFILE:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREPARE_SCRIPT="${SCRIPT_DIR}/prepare-test-battery.py"
SERVICE_MANAGER="${SCRIPT_DIR}/service-manager.sh"
RESULT_WRITER="${SCRIPT_DIR}/write-test-result.py"
BATTERY_NAME_HINT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["name"])' "${BATTERY_CONFIG_FILE}")"
BATTERY_RUNTIME_CONFIG_DIR="${RUNNER_TEMP:-${PWD}/build/runtime}/battery-config/${BATTERY_NAME_HINT}"
DUCKDB_BIN="${ARTIFACT_DIR}/bin/duckdb"

rm -rf "${BATTERY_RUNTIME_CONFIG_DIR}"
python3 "${PREPARE_SCRIPT}" "${BATTERY_CONFIG_FILE}" "${BATTERY_RUNTIME_CONFIG_DIR}"
# shellcheck disable=SC1091
source "${BATTERY_RUNTIME_CONFIG_DIR}/battery.env"
# shellcheck disable=SC1091
source "${SERVICE_MANAGER}"

LOG_DIR="${PWD}/build/logs/${BATTERY_NAME}"
RESULT_DIR="${PWD}/build/results/${BATTERY_NAME}"
RESULT_FILE="${RESULT_DIR}/result.json"
IGNORED_TEST_ROOT="${RUNNER_TEMP:-${PWD}/build/runtime}/ignored-tests/${BATTERY_NAME}"
RUNTIME_ROOT="${RUNNER_TEMP:-${PWD}/build/runtime}/${BATTERY_NAME}"
SERVICE_RUNTIME_ROOT="${RUNTIME_ROOT}/services"
BATTERY_LOG="${LOG_DIR}/battery-runner.log"
mkdir -p "${RUNTIME_ROOT}/home" "${RUNTIME_ROOT}/tmp" "${LOG_DIR}" "${RESULT_DIR}" "${IGNORED_TEST_ROOT}" "${LOG_DIR}/services"
export HOME="${RUNTIME_ROOT}/home"
export TMPDIR="${RUNTIME_ROOT}/tmp"

qa_log() {
  local level=$1
  shift
  local message=$*
  local timestamp
  timestamp="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  printf '%s [%s] [%s] %s\n' "${timestamp}" "${level}" "${BATTERY_NAME}" "${message}" | tee -a "${BATTERY_LOG}" >&2
}

qa_log INFO "battery runner started"
qa_log INFO "mode=$([[ "${QA_SERVICE_HOST_ONLY}" == "1" ]] && echo service-host || echo test) runner=${RUNNER_KIND} source=${UPSTREAM_ROOT} runtime=${RUNTIME_ROOT}"
qa_log INFO "config=${BATTERY_CONFIG_FILE} runtime_config=${BATTERY_RUNTIME_CONFIG_DIR}"

finalize_result() {
  local original_status=$?
  local writer_status=0
  trap - EXIT
  qa_log INFO "cleanup started exit_code=${original_status}"
  qa_service_stop_all || true

  if [[ "${QA_SERVICE_HOST_ONLY}" == "1" ]]; then
    qa_log INFO "service-host mode finished exit_code=${original_status}"
    exit "${original_status}"
  fi

  python3 "${RESULT_WRITER}" \
    --battery-config "${BATTERY_CONFIG_FILE}" \
    --log-dir "${LOG_DIR}" \
    --output "${RESULT_FILE}" \
    --exit-code "${original_status}" \
    --started-at-ms "${STARTED_AT_MS}" || writer_status=$?
  if [[ "${original_status}" -eq 0 && "${writer_status}" -ne 0 ]]; then
    original_status="${writer_status}"
  fi
  qa_log INFO "result finalized exit_code=${original_status} result=${RESULT_FILE}"
  exit "${original_status}"
}
trap finalize_result EXIT

write_service_environment() {
  local destination="${QA_SERVICE_ENV_FILE:?QA_SERVICE_ENV_FILE is required in service-host mode}"
  python3 - "${destination}" <<'PY'
import json
import os
import sys
from pathlib import Path

prefixes = (
    "PG", "POSTGRES_", "MSSQL_", "SQLSERVER_", "AZURE_", "AZ_",
    "DUCKDB_AZURE_", "HTTP_", "PYTHON_HTTP_", "TEST_", "AWS_", "S3_",
    "UC_", "UNITY_", "FIXTURE_", "VENDED_", "EQUALITY_",
)
exact = {
    "ENABLE_DATA_INTEGRITY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "BQ_TEST_PROJECT",
    "BQ_TEST_DATASET",
    "BQ_TEST_EXPORT_URI",
}
payload = {
    key: value
    for key, value in os.environ.items()
    if key in exact or key.startswith(prefixes)
}
path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"exported {len(payload)} service environment variables to {path}")
PY
}

wait_for_service_host_stop() {
  local ready_file="${QA_SERVICE_READY_FILE:?QA_SERVICE_READY_FILE is required in service-host mode}"
  local stop_file="${QA_SERVICE_STOP_FILE:?QA_SERVICE_STOP_FILE is required in service-host mode}"
  rm -f "${ready_file}" "${stop_file}"
  write_service_environment
  touch "${ready_file}"
  qa_log INFO "service host ready env_file=${QA_SERVICE_ENV_FILE} ready_file=${ready_file}"
  while [[ ! -f "${stop_file}" ]]; do
    sleep 1
  done
  qa_log INFO "service host stop signal received stop_file=${stop_file}"
}

# Service-host mode is deliberately infrastructure-only. It must not require or
# invoke the DuckDB runtime that is under test. The Windows runner consumes the
# exported environment and executes duckdb.exe/unittest.exe natively.
if [[ "${QA_SERVICE_HOST_ONLY}" == "1" ]]; then
  qa_log INFO "validating prerequisites for infrastructure host"
  qa_prerequisite_check_file "${BATTERY_RUNTIME_CONFIG_DIR}/prerequisites.json"
  qa_log INFO "starting battery-level services"
  qa_service_manager_init "${SERVICE_RUNTIME_ROOT}" "${UPSTREAM_ROOT}" "${LOG_DIR}/services"
  services_manifest="${BATTERY_RUNTIME_CONFIG_DIR}/services.json"
  qa_service_start_file "${services_manifest}"
  qa_log INFO "battery-level services started"
  if [[ -n "${QA_SERVICE_PROFILE}" ]]; then
    profile_services_manifest="${BATTERY_RUNTIME_CONFIG_DIR}/profile-services-${QA_SERVICE_PROFILE}.json"
    if [[ ! -f "${profile_services_manifest}" ]]; then
      qa_log ERROR "profile service manifest is missing profile=${QA_SERVICE_PROFILE} path=${profile_services_manifest}"
      exit 1
    fi
    qa_log INFO "starting profile services profile=${QA_SERVICE_PROFILE}"
    qa_service_start_file "${profile_services_manifest}"
    qa_log INFO "profile services started profile=${QA_SERVICE_PROFILE}"
  fi
  wait_for_service_host_stop
  exit 0
fi

# The upstream BigQuery suite uses the same project as its billing project in
# this repository. GitHub's auth action already creates a temporary JSON key
# file, so expose that same path to the service-account secret tests.
if [[ "${BATTERY_NAME}" == "bigquery" && -n "${BQ_TEST_PROJECT:-}" ]]; then
  export BQ_TEST_BILLING_PROJECT="${BQ_TEST_BILLING_PROJECT:-${BQ_TEST_PROJECT}}"
  if [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]]; then
    export BQ_TEST_SA_KEY_PATH="${BQ_TEST_SA_KEY_PATH:-${GOOGLE_APPLICATION_CREDENTIALS}}"
  fi
fi

# Services may invoke DuckDB while preparing fixtures on the Linux execution
# path. The Windows infrastructure-only path above intentionally bypasses this.
if [[ ! -x "${DUCKDB_BIN}" ]]; then
  qa_log ERROR "DuckDB runtime is missing or not executable: ${DUCKDB_BIN}"
  exit 1
fi
if [[ ! -x "${RESULT_WRITER}" ]]; then
  qa_log ERROR "Structured result writer is missing or not executable: ${RESULT_WRITER}"
  exit 1
fi
export PATH="$(cd "$(dirname "${DUCKDB_BIN}")" && pwd):${PATH}"
qa_log INFO "DuckDB test runtime=${DUCKDB_BIN}"

ignore_upstream_test() {
  local relative_path=$1
  local reason=$2
  local source_path="${UPSTREAM_ROOT}/${relative_path}"
  local target_path="${IGNORED_TEST_ROOT}/${relative_path}"

  if [[ ! -f "${source_path}" ]]; then
    qa_log ERROR "configured ignored test is missing: ${relative_path}"
    exit 1
  fi

  mkdir -p "$(dirname "${target_path}")"
  mv "${source_path}" "${target_path}"
  printf '%s\t%s\n' "${relative_path}" "${reason}" >>"${LOG_DIR}/ignored-tests.tsv"
  qa_log INFO "ignored test moved path=${relative_path} reason=${reason}"
}

while IFS=$'\t' read -r relative_path reason; do
  if [[ -n "${relative_path}" ]]; then
    ignore_upstream_test "${relative_path}" "${reason}"
  fi
done <"${BATTERY_RUNTIME_CONFIG_DIR}/ignored-global.tsv"

if [[ "${UPSTREAM_REF}" =~ ^[0-9a-fA-F]{40}$ ]]; then
  actual_commit="$(git -C "${UPSTREAM_ROOT}" rev-parse HEAD)"
  qa_log INFO "upstream commit expected=${UPSTREAM_REF} actual=${actual_commit}"
  if [[ "${actual_commit,,}" != "${UPSTREAM_REF,,}" ]]; then
    qa_log ERROR "${BATTERY_NAME} checkout must be ${UPSTREAM_REF}; found ${actual_commit}"
    exit 1
  fi
fi

prepare_bigquery_dynamic_tests() {
  python3 - "${UPSTREAM_ROOT}" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
test_root = root / "test" / "sql"
test_files = sorted(
    path
    for path in test_root.rglob("*")
    if path.is_file() and path.name.endswith((".test", ".test_slow", ".test_coverage"))
)

require_count = 0
location_count = 0
for path in test_files:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    filtered = [line for line in lines if line.strip() != "require bigquery"]
    require_count += len(lines) - len(filtered)
    text = "".join(filtered)
    location_count += text.count("europe-west3")
    text = text.replace("europe-west3", "EU")
    path.write_text(text, encoding="utf-8")

if require_count == 0:
    raise SystemExit("No BigQuery SQLLogicTest requirement guards were found")

public_dataset = test_root / "storage" / "attach_public_dataset.test"
text = public_dataset.read_text(encoding="utf-8")
old = "billing_project=${BQ_TEST_BILLING_PROJECT}"
new = "billing_project='${BQ_TEST_BILLING_PROJECT}'"
if old not in text:
    raise SystemExit("BigQuery billing project expression was not found")
public_dataset.write_text(text.replace(old, new, 1), encoding="utf-8")

jobs_test = test_root / "functions" / "function_bigquery_jobs.test"
text = jobs_test.read_text(encoding="utf-8")
old = "<REGEX>:[a-zA-Z0-9]+"
new = "<REGEX>:[a-zA-Z0-9-]+"
if old not in text:
    raise SystemExit("BigQuery project result regex was not found")
jobs_test.write_text(text.replace(old, new, 1), encoding="utf-8")

print(
    f"Adapted {require_count} BigQuery SQLLogicTest files for the dynamic runtime; "
    f"normalized {location_count} job locations to EU"
)
PY
}

# Upstream builds BigQuery into its unittest binary, while this repository
# installs and validates the community extension dynamically. The upstream
# `require bigquery` guard therefore cannot represent this runtime. The pinned
# suite also assumes a project ID without dashes and a europe-west3 dataset;
# adapt those environment-specific assumptions to this repository's EU dataset.
# validate-extension-probe.py still blocks execution unless BigQuery is installed
# and loaded successfully.
if [[ "${BATTERY_NAME}" == "bigquery" ]]; then
  qa_log INFO "adapting BigQuery dynamic SQLLogicTests"
  prepare_bigquery_dynamic_tests
fi

export ARTIFACT_DIR
export BATTERY_RUNTIME_CONFIG_DIR
export DUCKDB_VERSION
export MSSQL_RELEASE_TAG="${UPSTREAM_REF}"

qa_log INFO "validating prerequisites"
qa_prerequisite_check_file "${BATTERY_RUNTIME_CONFIG_DIR}/prerequisites.json"
qa_log INFO "starting battery-level services"
qa_service_manager_init "${SERVICE_RUNTIME_ROOT}" "${UPSTREAM_ROOT}" "${LOG_DIR}/services"
qa_service_start_file "${BATTERY_RUNTIME_CONFIG_DIR}/services.json"
qa_log INFO "battery-level services started"

status=0
qa_log INFO "executing runner kind=${RUNNER_KIND}"
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
    qa_log ERROR "unsupported test battery runner: ${RUNNER_KIND}"
    status=2
    ;;
esac
qa_log INFO "runner finished exit_code=${status}"

# Bash suppresses errexit inside functions invoked through `||`, so a failing
# Catch2 pipeline could previously be followed by a successful post-check and
# return zero. Treat any non-zero Catch2 failure summary as a battery failure.
if [[ "${status}" -eq 0 && "${RUNNER_KIND}" == "standard" ]] && \
   grep -R -E -q 'test cases?:.*\|[[:space:]]*[1-9][0-9]* failed' "${LOG_DIR}"/unittest-*.log 2>/dev/null; then
  qa_log ERROR "DuckDB unittest reported failing test cases"
  status=1
fi

exit "${status}"
