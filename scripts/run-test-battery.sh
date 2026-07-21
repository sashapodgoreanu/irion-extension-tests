#!/usr/bin/env bash
set -Eeuo pipefail

RUNNER_KIND="${1:?runner kind is required}"
BATTERY_NAME="${2:?battery name is required}"
UPSTREAM_ROOT="${3:?upstream root is required}"
TEST_FILTER="${4:?test filter is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "${RUNNER_KIND}" in
  standard)
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
