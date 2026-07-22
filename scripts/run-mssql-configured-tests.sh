#!/usr/bin/env bash
set -Eeuo pipefail

UPSTREAM_ROOT="${1:?MSSQL upstream root is required}"
TEST_PATH="${2:-test/sql/*}"
ARTIFACT_DIR="${ARTIFACT_DIR:-build/artifact}"
BATTERY_RUNTIME_CONFIG_DIR="${BATTERY_RUNTIME_CONFIG_DIR:?battery runtime config directory is required}"
MSSQL_RELEASE_TAG="${MSSQL_RELEASE_TAG:?MSSQL release tag is required}"
DUCKDB_VERSION="${DUCKDB_VERSION:?DuckDB version is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_RUNNER_SOURCE="${SCRIPT_DIR}/run-mssql-tests-base.sh"
BASE_RUNNER_PATCHER="${SCRIPT_DIR}/prepare-mssql-configured-runner.py"
TEST_PATCHER="${SCRIPT_DIR}/prepare-mssql-release-tests.py"
FIXTURE_PATCHER="${SCRIPT_DIR}/prepare-mssql-master-fixture.py"
REQUIREMENT_CHECKER="${SCRIPT_DIR}/check-test-requirements.py"
RUNTIME_ROOT="${RUNNER_TEMP:-${PWD}/build/runtime}/mssql"
LOG_DIR="${PWD}/build/logs/mssql"
PATCHED_BASE_RUNNER="${RUNTIME_ROOT}/run-mssql-tests-base.sh"
UNITTEST_LOG="${LOG_DIR}/unittest.log"
EXTENSIONS_JSON="${BATTERY_RUNTIME_CONFIG_DIR}/extensions.json"

mkdir -p "${RUNTIME_ROOT}" "${LOG_DIR}"

for required in \
  "${BASE_RUNNER_SOURCE}" \
  "${BASE_RUNNER_PATCHER}" \
  "${TEST_PATCHER}" \
  "${FIXTURE_PATCHER}" \
  "${REQUIREMENT_CHECKER}" \
  "${BATTERY_RUNTIME_CONFIG_DIR}/install-extensions.sql" \
  "${BATTERY_RUNTIME_CONFIG_DIR}/init-extensions.sql" \
  "${EXTENSIONS_JSON}"; do
  if [[ ! -e "${required}" ]]; then
    echo "Required configured MSSQL input is missing: ${required}" >&2
    exit 1
  fi
done

actual_tag="$(git -C "${UPSTREAM_ROOT}" describe --tags --exact-match 2>/dev/null || true)"
if [[ "${actual_tag}" != "${MSSQL_RELEASE_TAG}" ]]; then
  echo "MSSQL checkout must be exactly ${MSSQL_RELEASE_TAG}; found ${actual_tag:-an untagged commit}" >&2
  exit 1
fi

python3 "${TEST_PATCHER}" \
  "${UPSTREAM_ROOT}" \
  "${LOG_DIR}/mssql-test-patches.json"
python3 "${FIXTURE_PATCHER}" \
  "${UPSTREAM_ROOT}" \
  "${LOG_DIR}/mssql-master-fixture.json"
python3 "${BASE_RUNNER_PATCHER}" \
  "${BASE_RUNNER_SOURCE}" \
  "${PATCHED_BASE_RUNNER}" \
  "${DUCKDB_VERSION}"

# The legacy base runner consumes these paths. They are generated for this job
# from config/extensions.yml and placed next to the runtime copy of the runner.
cp "${BATTERY_RUNTIME_CONFIG_DIR}/install-extensions.sql" \
  "${RUNTIME_ROOT}/install-extensions.sql"
cp "${BATTERY_RUNTIME_CONFIG_DIR}/init-extensions.sql" \
  "${RUNTIME_ROOT}/init-extensions.sql"
cp "${BATTERY_RUNTIME_CONFIG_DIR}/battery.json" "${LOG_DIR}/battery.json"
cp "${EXTENSIONS_JSON}" "${LOG_DIR}/extensions.json"

status=0
MSSQL_RELEASE_TAG="${MSSQL_RELEASE_TAG}" \
DUCKDB_VERSION="${DUCKDB_VERSION}" \
bash "${PATCHED_BASE_RUNNER}" "${UPSTREAM_ROOT}" "${TEST_PATH}" || status=$?

if [[ -f "${UNITTEST_LOG}" ]]; then
  python3 "${REQUIREMENT_CHECKER}" "${UNITTEST_LOG}" "${EXTENSIONS_JSON}" || status=$?
fi

exit "${status}"
