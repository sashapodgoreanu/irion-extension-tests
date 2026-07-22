#!/usr/bin/env bash
set -Eeuo pipefail

UPSTREAM_ROOT="${1:?Postgres scanner upstream root is required}"
TEST_FILTER="${2:-test/sql/*}"
EXPECTED_COMMIT="${3:?Postgres scanner commit is required}"
ARTIFACT_DIR="${ARTIFACT_DIR:-build/artifact}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_RUNNER="${SCRIPT_DIR}/run-tests.sh"
DUCKDB_BIN="${ARTIFACT_DIR}/bin/duckdb"
RUNTIME_ROOT="${RUNNER_TEMP:-${PWD}/build/runtime}/postgres_scanner"
LOG_DIR="${PWD}/build/logs/postgres_scanner"
FIXTURE_SCRIPT="${UPSTREAM_ROOT}/create-postgres-tables.sh"
UNITTEST_LOG="${LOG_DIR}/unittest-all.log"

mkdir -p "${RUNTIME_ROOT}/home" "${RUNTIME_ROOT}/tmp" "${LOG_DIR}/services"
export HOME="${RUNTIME_ROOT}/home"
export TMPDIR="${RUNTIME_ROOT}/tmp"
export PATH="$(cd "$(dirname "${DUCKDB_BIN}")" && pwd):${PATH}"

export PGHOST="${PGHOST:-localhost}"
export PGPORT="${PGPORT:-5432}"
export PGUSER="${PGUSER:-postgres}"
export PGPASSWORD="${PGPASSWORD:-postgres}"
export PGDATABASE="${PGDATABASE:-postgres}"
export POSTGRES_TEST_DATABASE_AVAILABLE=1
export POSTGRES_TEST_SLOW=1
export PGSCANNERTMP_ABS_DIR_PREFIX="${RUNTIME_ROOT}/tmp"

for required in \
  "${DUCKDB_BIN}" \
  "${BASE_RUNNER}" \
  "${FIXTURE_SCRIPT}"; do
  if [[ ! -e "${required}" ]]; then
    echo "Required Postgres scanner test input is missing: ${required}" >&2
    exit 1
  fi
done

ACTUAL_COMMIT="$(git -C "${UPSTREAM_ROOT}" rev-parse HEAD)"
if [[ "${ACTUAL_COMMIT}" != "${EXPECTED_COMMIT}" ]]; then
  echo "Postgres scanner checkout must be ${EXPECTED_COMMIT}; found ${ACTUAL_COMMIT}" >&2
  exit 1
fi

for _ in $(seq 1 60); do
  if pg_isready -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! pg_isready -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" >/dev/null 2>&1; then
  echo "PostgreSQL test service did not become ready" >&2
  exit 1
fi

{
  echo "expected_commit=${EXPECTED_COMMIT}"
  echo "actual_commit=${ACTUAL_COMMIT}"
  echo "test_filter=${TEST_FILTER}"
  echo "postgres_host=${PGHOST}"
  echo "postgres_port=${PGPORT}"
  echo "postgres_user=${PGUSER}"
} >"${LOG_DIR}/postgres-scanner-info.txt"

"${DUCKDB_BIN}" -csv -header -c "
  INSTALL tpch;
  INSTALL tpcds;
  INSTALL postgres_scanner;
  LOAD postgres_scanner;
  SELECT extension_name, installed, loaded, extension_version, install_mode, installed_from
  FROM duckdb_extensions()
  WHERE extension_name = 'postgres_scanner';
" | tee "${LOG_DIR}/postgres-scanner-extension.csv"

python3 - "${LOG_DIR}/postgres-scanner-extension.csv" "${EXPECTED_COMMIT}" <<'PY'
import csv
import sys
from pathlib import Path

rows = list(csv.DictReader(Path(sys.argv[1]).open(encoding="utf-8")))
if len(rows) != 1:
    raise SystemExit("Postgres scanner probe did not return exactly one extension row")
row = rows[0]
if row.get("installed", "").lower() != "true" or row.get("loaded", "").lower() != "true":
    raise SystemExit("Postgres scanner probe did not install and load the extension")
reported_commit = row.get("extension_version", "").lower().removeprefix("v")
expected_commit = sys.argv[2].lower()
if len(reported_commit) < 7 or not expected_commit.startswith(reported_commit):
    raise SystemExit(
        "Postgres scanner source/binary commit mismatch: "
        f"tests use {expected_commit}, binary reports {reported_commit or '<empty>'}"
    )
print(f"Postgres scanner release alignment verified: {expected_commit} -> {reported_commit}")
PY

(
  cd "${UPSTREAM_ROOT}"
  source ./create-postgres-tables.sh
  psql -d postgresscanner -c "SELECT 42"
  psql -d postgresscanner -c "SELECT * FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
) 2>&1 | tee "${LOG_DIR}/services/postgres-fixtures.log"

status=0
bash "${BASE_RUNNER}" \
  "postgres_scanner" \
  "${UPSTREAM_ROOT}" \
  "${TEST_FILTER}" || status=$?

if [[ -f "${UNITTEST_LOG}" ]] && grep -Eq '^require-env (POSTGRES_TEST_DATABASE_AVAILABLE|POSTGRES_TEST_SLOW): [1-9][0-9]*$' "${UNITTEST_LOG}"; then
  echo "Mandatory Postgres scanner integration tests were skipped" >&2
  grep -E '^require-env POSTGRES_TEST' "${UNITTEST_LOG}" >&2 || true
  status=1
fi

exit "${status}"
