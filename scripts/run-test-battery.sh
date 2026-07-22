#!/usr/bin/env bash
set -Eeuo pipefail

BATTERY_CONFIG_FILE="${1:?resolved battery JSON is required}"
UPSTREAM_ROOT="${2:?upstream root is required}"
ARTIFACT_DIR="${ARTIFACT_DIR:-build/artifact}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREPARE_SCRIPT="${SCRIPT_DIR}/prepare-test-battery.py"
BATTERY_NAME_HINT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["name"])' "${BATTERY_CONFIG_FILE}")"
BATTERY_RUNTIME_CONFIG_DIR="${RUNNER_TEMP:-${PWD}/build/runtime}/battery-config/${BATTERY_NAME_HINT}"

rm -rf "${BATTERY_RUNTIME_CONFIG_DIR}"
python3 "${PREPARE_SCRIPT}" "${BATTERY_CONFIG_FILE}" "${BATTERY_RUNTIME_CONFIG_DIR}"
# shellcheck disable=SC1091
source "${BATTERY_RUNTIME_CONFIG_DIR}/battery.env"

LOG_DIR="${PWD}/build/logs/${BATTERY_NAME}"
IGNORED_TEST_ROOT="${RUNNER_TEMP:-${PWD}/build/runtime}/ignored-tests/${BATTERY_NAME}"
mkdir -p "${LOG_DIR}" "${IGNORED_TEST_ROOT}"

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

case "${RUNNER_KIND}" in
  standard)
    exec bash "${SCRIPT_DIR}/run-standard-tests.sh" \
      "${BATTERY_NAME}" \
      "${UPSTREAM_ROOT}" \
      "${TEST_FILTER}"
    ;;
  postgres-scanner)
    exec bash "${SCRIPT_DIR}/run-postgres-scanner-tests.sh" \
      "${UPSTREAM_ROOT}" \
      "${TEST_FILTER}" \
      "${UPSTREAM_REF}"
    ;;
  mssql-release)
    exec bash "${SCRIPT_DIR}/run-mssql-configured-tests.sh" \
      "${UPSTREAM_ROOT}" \
      "${TEST_FILTER}"
    ;;
  *)
    echo "Unsupported test battery runner: ${RUNNER_KIND}" >&2
    exit 2
    ;;
esac
