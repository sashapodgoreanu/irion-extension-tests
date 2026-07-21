#!/usr/bin/env bash
set -Eeuo pipefail

RUNNER_KIND="${1:?runner kind is required}"
BATTERY_NAME="${2:?battery name is required}"
UPSTREAM_ROOT="${3:?upstream root is required}"
TEST_FILTER="${4:?test filter is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${PWD}/build/logs/${BATTERY_NAME}"
IGNORED_TEST_ROOT="${RUNNER_TEMP:-${PWD}/build/runtime}/ignored-tests/${BATTERY_NAME}"

ignore_upstream_test() {
  local relative_path=$1
  local reason=$2
  local source_path="${UPSTREAM_ROOT}/${relative_path}"
  local target_path="${IGNORED_TEST_ROOT}/${relative_path}"

  if [[ ! -f "${source_path}" ]]; then
    echo "Configured ignored test is missing: ${relative_path}" >&2
    exit 1
  fi

  mkdir -p "$(dirname "${target_path}")" "${LOG_DIR}"
  mv "${source_path}" "${target_path}"
  printf '%s\t%s\n' "${relative_path}" "${reason}" >>"${LOG_DIR}/ignored-tests.tsv"
}

case "${RUNNER_KIND}" in
  standard)
    if [[ "${BATTERY_NAME}" == "httpfs" ]]; then
      ignore_upstream_test \
        "test/extension/autoloading_base.test" \
        "Assumes no dynamically installed extensions, while the compatibility battery intentionally preloads five extensions"
    fi

    exec bash "${SCRIPT_DIR}/run-tests.sh" \
      "${BATTERY_NAME}" \
      "${UPSTREAM_ROOT}" \
      "${TEST_FILTER}"
    ;;
  mssql-release)
    exec bash "${SCRIPT_DIR}/run-mssql-tests.sh" \
      "${UPSTREAM_ROOT}" \
      "${TEST_FILTER}"
    ;;
  *)
    echo "Unsupported test battery runner: ${RUNNER_KIND}" >&2
    exit 2
    ;;
esac
