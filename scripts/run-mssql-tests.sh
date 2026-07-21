#!/usr/bin/env bash
set -Eeuo pipefail

UPSTREAM_ROOT="${1:?MSSQL upstream root is required}"
ARTIFACT_DIR="${ARTIFACT_DIR:-build/artifact}"
MSSQL_RELEASE_TAG="${MSSQL_RELEASE_TAG:-v0.2.1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_RUNNER="${SCRIPT_DIR}/run-mssql-tests-base.sh"
TEST_PATCHER="${SCRIPT_DIR}/prepare-mssql-release-tests.py"
FIXTURE_PATCHER="${SCRIPT_DIR}/prepare-mssql-master-fixture.py"
MSSQL_SHARED_INIT_SCRIPT="${SCRIPT_DIR}/init-extensions.sql"
DUCKDB_BIN="${ARTIFACT_DIR}/bin/duckdb"
RUNTIME_ROOT="${RUNNER_TEMP:-${PWD}/build/runtime}/mssql"
LOG_DIR="${PWD}/build/logs/mssql"
UNITTEST_LOG="${LOG_DIR}/unittest.log"

# AI MAINTAINER NOTE — MSSQL v0.2.1 TEST COMPATIBILITY LAYER
# -----------------------------------------------------------------------------
# Keep the published MSSQL binary and source checkout pinned to v0.2.1. This
# wrapper fixes only test/fixture defects that upstream discovered when issue
# #192 enabled SQLLogicTest in CI for the first time. Never copy implementation
# files from main into this checkout and never compile MSSQL into DuckDB.
#
# The preserved base runner still owns the dynamic community installation:
#   INSTALL mssql FROM community;
#   LOAD mssql;
# and the LOCAL_EXTENSION_REPO handling required by `require mssql`.
#
# This compatibility layer adds only:
#   - deterministic test-side fixes already accepted upstream;
#   - the missing master.dbo.test seed fixture;
#   - the core Azure extension needed by local, credential-free secret tests.

mkdir -p "${RUNTIME_ROOT}/home" "${RUNTIME_ROOT}/tmp" "${LOG_DIR}"
export HOME="${RUNTIME_ROOT}/home"
export TMPDIR="${RUNTIME_ROOT}/tmp"

for required in \
  "${BASE_RUNNER}" \
  "${TEST_PATCHER}" \
  "${FIXTURE_PATCHER}" \
  "${MSSQL_SHARED_INIT_SCRIPT}" \
  "${DUCKDB_BIN}"; do
  if [[ ! -e "${required}" ]]; then
    echo "Required MSSQL compatibility input is missing: ${required}" >&2
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

# Two v0.2.1 tests exercise only local Azure secret definitions. They do not need
# Azure credentials or a remote Azure SQL service, but `require azure` still needs
# the official dynamic Azure extension to be installed and available in the same
# isolated HOME that the base runner copies into LOCAL_EXTENSION_REPO.
"${DUCKDB_BIN}" -csv -header -c "
  INSTALL azure;
  LOAD azure;
  SELECT extension_name, installed, loaded, extension_version, install_mode, installed_from
  FROM duckdb_extensions()
  WHERE extension_name = 'azure';
" | tee "${LOG_DIR}/azure-extension.csv"

AZURE_EXTENSION_PATH="$(find "${HOME}/.duckdb/extensions" \
  -type f -path '*/v1.5.4/linux_amd64/azure.duckdb_extension' -print -quit)"
if [[ -z "${AZURE_EXTENSION_PATH}" ]]; then
  echo "The official Azure extension was not installed in the isolated MSSQL HOME" >&2
  exit 1
fi
printf '%s\n' "${AZURE_EXTENSION_PATH}" >"${LOG_DIR}/azure-extension-path.txt"

# The base runner creates its MSSQL-only init profile from this shared file and
# removes only LOAD mssql. Append Azure in this isolated job checkout so every
# SQLLogicTest connection loads the already installed dynamic Azure binary. Other
# matrix jobs use separate checkouts and are unaffected.
if ! grep -Eiq '^[[:space:]]*LOAD[[:space:]]+azure[[:space:]]*;[[:space:]]*$' "${MSSQL_SHARED_INIT_SCRIPT}"; then
  printf '\n# MSSQL battery: local Azure secret tests require the dynamic Azure extension.\nLOAD azure;\n' \
    >>"${MSSQL_SHARED_INIT_SCRIPT}"
fi
cp "${MSSQL_SHARED_INIT_SCRIPT}" "${LOG_DIR}/init-extensions-with-azure.sql"

status=0
bash "${BASE_RUNNER}" "$@" || status=$?

# `require` misses are reported as skips, not failures. Treat an Azure miss as a
# broken test environment so the battery cannot become green by silently omitting
# azure_secret_token_only.test and azure_device_code.test.
if [[ -f "${UNITTEST_LOG}" ]] && grep -Eq '^require azure: [1-9][0-9]*$' "${UNITTEST_LOG}"; then
  echo "Azure SQLLogicTests were skipped because the dynamic extension was unavailable" >&2
  grep -E '^require azure: ' "${UNITTEST_LOG}" >&2 || true
  status=1
fi

exit "${status}"
