#!/usr/bin/env bash
set -Eeuo pipefail

UPSTREAM_ROOT="${1:?MSSQL upstream root is required}"
TEST_PATH="${2:-test/sql/*}"
ARTIFACT_DIR="${ARTIFACT_DIR:-build/artifact}"
MSSQL_RELEASE_TAG="${MSSQL_RELEASE_TAG:-v0.2.1}"
MSSQL_RELEASE_VERSION="${MSSQL_RELEASE_TAG#v}"

DUCKDB_BIN="${ARTIFACT_DIR}/bin/duckdb"
UNITTEST_BIN="${ARTIFACT_DIR}/bin/unittest"
RUNTIME_ROOT="${RUNNER_TEMP:-${PWD}/build/runtime}/mssql"
LOG_DIR="${PWD}/build/logs/mssql"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_SCRIPT="${SCRIPT_DIR}/install-extensions.sql"
INIT_SCRIPT="${SCRIPT_DIR}/init-extensions.sql"
COMPOSE_FILE="${UPSTREAM_ROOT}/docker/docker-compose.yml"
UPSTREAM_INTEGRATION_SCRIPT="${UPSTREAM_ROOT}/scripts/ci/integration_test.sh"
TEST_CONFIG="${RUNTIME_ROOT}/mssql-test-config.json"
EXTENSION_CSV="${LOG_DIR}/extensions.csv"

mkdir -p "${RUNTIME_ROOT}/home" "${RUNTIME_ROOT}/tmp" "${LOG_DIR}/services"
export HOME="${RUNTIME_ROOT}/home"
export TMPDIR="${RUNTIME_ROOT}/tmp"
export PATH="$(cd "$(dirname "${DUCKDB_BIN}")" && pwd):${PATH}"

export MSSQL_TEST_HOST="${MSSQL_TEST_HOST:-localhost}"
export MSSQL_TEST_PORT="${MSSQL_TEST_PORT:-1433}"
export MSSQL_TEST_USER="${MSSQL_TEST_USER:-sa}"
export MSSQL_TEST_PASS="${MSSQL_TEST_PASS:-TestPassword1}"
export MSSQL_TEST_DB="${MSSQL_TEST_DB:-master}"
export MSSQL_TEST_DSN="${MSSQL_TEST_DSN:-Server=${MSSQL_TEST_HOST},${MSSQL_TEST_PORT};Database=${MSSQL_TEST_DB};User Id=${MSSQL_TEST_USER};Password=${MSSQL_TEST_PASS}}"
export MSSQL_TEST_URI="${MSSQL_TEST_URI:-mssql://${MSSQL_TEST_USER}:${MSSQL_TEST_PASS}@${MSSQL_TEST_HOST}:${MSSQL_TEST_PORT}/${MSSQL_TEST_DB}}"
export MSSQL_TESTDB_DSN="${MSSQL_TESTDB_DSN:-Server=${MSSQL_TEST_HOST},${MSSQL_TEST_PORT};Database=TestDB;User Id=${MSSQL_TEST_USER};Password=${MSSQL_TEST_PASS}}"
export MSSQL_TESTDB_URI="${MSSQL_TESTDB_URI:-mssql://${MSSQL_TEST_USER}:${MSSQL_TEST_PASS}@${MSSQL_TEST_HOST}:${MSSQL_TEST_PORT}/TestDB}"
export MSSQL_TEST_SERVER="${MSSQL_TEST_SERVER:-${MSSQL_TEST_DSN}}"
export MSSQL_TEST_CONNECTION_STRING="${MSSQL_TEST_CONNECTION_STRING:-${MSSQL_TEST_DSN}}"

# AI MAINTAINER NOTE — RELEASE PINNING CONTRACT
# ------------------------------------------------------------
# This battery intentionally follows a RELEASE TAG, never `main`.
# When maintaining this file in the future:
#   1. Find the latest published release of hugr-lab/mssql-extension.
#   2. Update MSSQL_RELEASE_TAG in config/extensions.yml and the workflow together.
#   3. Confirm DuckDB community-extensions points at the same tag/version.
#   4. Keep using the Docker/SQL/test files from that pinned checkout; do not copy
#      their contents into this repository, because upstream test changes must be
#      observed when the release pin is deliberately advanced.
#   5. Do not replace the tag with a moving branch or commit selected from `main`.
#
# IMPORTANT: DuckDB community extension metadata currently exposes the source
# commit abbreviation in duckdb_extensions().extension_version, not necessarily
# the semantic release version. Therefore validate the exact release tag first,
# then validate that extension_version is a valid prefix of that tag's commit SHA.
# Do not compare extension_version directly with values such as "0.2.1".

cleanup() {
  if [[ "${MSSQL_COMPOSE_STARTED:-0}" == "1" ]]; then
    docker compose -f "${COMPOSE_FILE}" logs --no-color \
      >"${LOG_DIR}/services/sqlserver-compose.log" 2>&1 || true
    docker compose -f "${COMPOSE_FILE}" down --volumes --remove-orphans \
      >>"${LOG_DIR}/services/sqlserver-compose.log" 2>&1 || true
  fi
}
trap cleanup EXIT

for required in "${DUCKDB_BIN}" "${UNITTEST_BIN}" "${COMPOSE_FILE}" "${UPSTREAM_INTEGRATION_SCRIPT}"; do
  if [[ ! -e "${required}" ]]; then
    echo "Required MSSQL test input is missing: ${required}" >&2
    exit 1
  fi
done

actual_tag="$(git -C "${UPSTREAM_ROOT}" describe --tags --exact-match 2>/dev/null || true)"
if [[ "${actual_tag}" != "${MSSQL_RELEASE_TAG}" ]]; then
  echo "MSSQL checkout must be exactly ${MSSQL_RELEASE_TAG}; found ${actual_tag:-an untagged commit}" >&2
  exit 1
fi

UPSTREAM_COMMIT="$(git -C "${UPSTREAM_ROOT}" rev-parse HEAD)"
UPSTREAM_SHORT_COMMIT="$(git -C "${UPSTREAM_ROOT}" rev-parse --short=7 HEAD)"

{
  echo "release_tag=${MSSQL_RELEASE_TAG}"
  echo "release_version=${MSSQL_RELEASE_VERSION}"
  echo "upstream_commit=${UPSTREAM_COMMIT}"
  echo "upstream_short_commit=${UPSTREAM_SHORT_COMMIT}"
  echo "test_path=${TEST_PATH}"
} >"${LOG_DIR}/test-info.txt"

INSTALL_SQL="$(sed '/^[[:space:]]*--/d' "${INSTALL_SCRIPT}" | tr '\n' ' ')"
INIT_SQL="$(sed '/^[[:space:]]*--/d' "${INIT_SCRIPT}" | tr '\n' ' ')"

# install-extensions.sql contains `INSTALL mssql FROM community;` and
# init-extensions.sql contains `LOAD mssql;`. Keep both explicit: FROM community
# belongs to INSTALL only; LOAD resolves the already installed community binary.
"${DUCKDB_BIN}" -csv -header -c "${INSTALL_SQL} ${INIT_SQL}
  SELECT extension_name, installed, loaded, extension_version, install_mode, installed_from
  FROM duckdb_extensions()
  WHERE extension_name IN ('ducklake', 'httpfs', 'mssql')
  ORDER BY extension_name;" \
  | tee "${EXTENSION_CSV}"

python3 - "${EXTENSION_CSV}" "${UPSTREAM_COMMIT}" "${MSSQL_RELEASE_TAG}" <<'PY'
import csv
import sys
from pathlib import Path

rows = list(csv.DictReader(Path(sys.argv[1]).open(encoding="utf-8")))
expected_commit = sys.argv[2].lower()
release_tag = sys.argv[3]
by_name = {row["extension_name"]: row for row in rows}

for name in ("ducklake", "httpfs", "mssql"):
    row = by_name.get(name)
    if not row:
        raise SystemExit(f"{name} is missing from duckdb_extensions()")
    if row.get("installed", "").lower() != "true":
        raise SystemExit(f"{name} is not installed")
    if row.get("loaded", "").lower() != "true":
        raise SystemExit(f"{name} is not loaded")

mssql = by_name["mssql"]
installed_from = mssql.get("installed_from", "").lower()
if installed_from != "community":
    raise SystemExit(
        "MSSQL was not installed from the community repository: "
        f"installed_from={installed_from or '<empty>'}"
    )

reported_commit = mssql.get("extension_version", "").lower().removeprefix("v")
if len(reported_commit) < 7 or not expected_commit.startswith(reported_commit):
    raise SystemExit(
        "MSSQL source/binary commit mismatch: "
        f"tests use {release_tag} at {expected_commit}, "
        f"community binary reports {reported_commit or '<empty>'}"
    )

print(
    "MSSQL release alignment verified: "
    f"{release_tag} -> {expected_commit}, community binary -> {reported_commit}"
)
PY

MSSQL_EXTENSION_PATH="$(find "${HOME}/.duckdb/extensions" \
  -type f -path '*/v1.5.4/linux_amd64/mssql.duckdb_extension' -print -quit)"
if [[ -z "${MSSQL_EXTENSION_PATH}" ]]; then
  echo "The installed MSSQL community extension binary was not found" >&2
  exit 1
fi
printf '%s\n' "${MSSQL_EXTENSION_PATH}" >"${LOG_DIR}/mssql-extension-path.txt"

cat >"${UPSTREAM_ROOT}/.env" <<EOF
MSSQL_TEST_HOST=${MSSQL_TEST_HOST}
MSSQL_TEST_PORT=${MSSQL_TEST_PORT}
MSSQL_TEST_USER=${MSSQL_TEST_USER}
MSSQL_TEST_PASS=${MSSQL_TEST_PASS}
MSSQL_TEST_DB=${MSSQL_TEST_DB}
EOF

docker compose -f "${COMPOSE_FILE}" up -d sqlserver
export MSSQL_COMPOSE_STARTED=1
SQLSERVER_ID="$(docker compose -f "${COMPOSE_FILE}" ps -q sqlserver)"
if [[ -z "${SQLSERVER_ID}" ]]; then
  echo "SQL Server container was not created" >&2
  exit 1
fi

for _ in $(seq 1 60); do
  if docker exec "${SQLSERVER_ID}" /opt/mssql-tools18/bin/sqlcmd \
      -S localhost -U "${MSSQL_TEST_USER}" -P "${MSSQL_TEST_PASS}" -C \
      -Q 'SELECT 1' >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! docker exec "${SQLSERVER_ID}" /opt/mssql-tools18/bin/sqlcmd \
    -S localhost -U "${MSSQL_TEST_USER}" -P "${MSSQL_TEST_PASS}" -C \
    -Q 'SELECT 1' >/dev/null 2>&1; then
  echo "SQL Server did not become ready" >&2
  exit 1
fi

seed_sql() {
  local source=$1
  local target="/tmp/$(basename "${source}")"
  if [[ ! -f "${source}" ]]; then
    echo "Pinned upstream seed script is missing: ${source}" >&2
    return 1
  fi

  docker cp "${source}" "${SQLSERVER_ID}:${target}"
  docker exec "${SQLSERVER_ID}" /opt/mssql-tools18/bin/sqlcmd \
    -S localhost -U "${MSSQL_TEST_USER}" -P "${MSSQL_TEST_PASS}" -C \
    -i "${target}"
}

# Reuse the release's own database fixtures. Do not fork these SQL files locally.
seed_sql "${UPSTREAM_ROOT}/docker/init/init.sql" \
  | tee "${LOG_DIR}/services/init.log"
seed_sql "${UPSTREAM_ROOT}/docker/init/init-transaction-tests.sql" \
  | tee "${LOG_DIR}/services/init-transaction-tests.log"

# The v0.2.1 release script performs its official connectivity/smoke test.
# The full SQLLogicTest folder is run immediately afterwards because this release
# predates the upstream CI change that passed `unittest` into this script.
bash "${UPSTREAM_INTEGRATION_SCRIPT}" "${DUCKDB_BIN}" "${MSSQL_EXTENSION_PATH}" \
  2>&1 | tee "${LOG_DIR}/upstream-integration-smoke.log"

"${DUCKDB_BIN}" --unsigned -c "
  LOAD '${MSSQL_EXTENSION_PATH}';
  ATTACH '${MSSQL_TESTDB_DSN}' AS seedcheck (TYPE mssql);
  SELECT count(*) FROM seedcheck.dbo.TestSimplePK;
" >"${LOG_DIR}/seed-check.log"

CONNECTION_SQL="${INIT_SQL}"
python3 - "${TEST_CONFIG}" "${INIT_SCRIPT}" "${CONNECTION_SQL}" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
init_script = sys.argv[2]
on_new_connection = sys.argv[3]
config = {
    "description": "Pinned MSSQL community release tests with HTTPFS and DuckLake loaded",
    "autoloading": "all",
    "init_script": init_script,
    "on_new_connection": on_new_connection,
    # This field is the SQLLogicTest capability declaration used by `require`.
    # It does not change how the binary is obtained: mssql is still installed by
    # `INSTALL mssql FROM community` and loaded dynamically by `LOAD mssql`.
    "statically_loaded_extensions": ["core_functions", "parquet", "mssql"],
    "summarize_failures": True,
}
config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
PY
cp "${TEST_CONFIG}" "${LOG_DIR}/mssql-test-config.json"

UNITTEST_LOG="${LOG_DIR}/unittest.log"
"${UNITTEST_BIN}" \
  --test-config "${TEST_CONFIG}" \
  --test-dir "${UPSTREAM_ROOT}" \
  "${TEST_PATH}" \
  2>&1 | tee "${UNITTEST_LOG}"

if grep -Eq '^require mssql: [1-9][0-9]*$' "${UNITTEST_LOG}"; then
  echo "MSSQL tests were skipped because the extension was not recognized" >&2
  exit 1
fi

if grep -Eq '^require-env (MSSQL_TEST_DSN|MSSQL_TEST_URI|MSSQL_TESTDB_DSN|MSSQL_TESTDB_URI|MSSQL_TEST_SERVER|MSSQL_TEST_CONNECTION_STRING): [1-9][0-9]*$' "${UNITTEST_LOG}"; then
  echo "Mandatory MSSQL integration variables were skipped" >&2
  grep -E '^require-env MSSQL_TEST' "${UNITTEST_LOG}" >&2 || true
  exit 1
fi

if ! grep -Eq '([1-9][0-9]* test cases|test cases:[[:space:]]+[1-9][0-9]*)' "${UNITTEST_LOG}"; then
  echo "The MSSQL SQLLogicTest run did not report any executed test cases" >&2
  exit 1
fi
