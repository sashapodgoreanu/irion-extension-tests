#!/usr/bin/env bash
set -Eeuo pipefail

UPSTREAM_ROOT="${1:?Postgres scanner upstream root is required}"
TEST_FILTER="${2:-test/sql/*}"
EXPECTED_COMMIT="${3:?Postgres scanner commit is required}"
ARTIFACT_DIR="${ARTIFACT_DIR:-build/artifact}"
BATTERY_RUNTIME_CONFIG_DIR="${BATTERY_RUNTIME_CONFIG_DIR:?battery runtime config directory is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STANDARD_RUNNER="${SCRIPT_DIR}/run-standard-tests.sh"
DUCKDB_BIN="${ARTIFACT_DIR}/bin/duckdb"
RUNTIME_ROOT="${RUNNER_TEMP:-${PWD}/build/runtime}/postgres_scanner"
LOG_DIR="${PWD}/build/logs/postgres_scanner"
FIXTURE_SCRIPT="${UPSTREAM_ROOT}/create-postgres-tables.sh"
INSTALL_SCRIPT="${BATTERY_RUNTIME_CONFIG_DIR}/install-extensions.sql"
INIT_SCRIPT="${BATTERY_RUNTIME_CONFIG_DIR}/init-extensions.sql"
EXTENSIONS_JSON="${BATTERY_RUNTIME_CONFIG_DIR}/extensions.json"
PROBE_VALIDATOR="${SCRIPT_DIR}/validate-extension-probe.py"
UNITTEST_LOG="${LOG_DIR}/unittest-all.log"
RUNNER_LOG="${LOG_DIR}/postgres-scanner-runner.log"

mkdir -p "${RUNTIME_ROOT}/home" "${RUNTIME_ROOT}/tmp" "${LOG_DIR}/services"
export HOME="${RUNTIME_ROOT}/home"
export TMPDIR="${RUNTIME_ROOT}/tmp"
export PATH="$(cd "$(dirname "${DUCKDB_BIN}")" && pwd):${PATH}"

pg_log() {
  local level=$1
  shift
  local timestamp
  timestamp="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  printf '%s [%s] [postgres_scanner] %s\n' "${timestamp}" "${level}" "$*" | tee -a "${RUNNER_LOG}" >&2
}

export PGHOST="${PGHOST:-localhost}"
export PGPORT="${PGPORT:-5432}"
export PGUSER="${PGUSER:-postgres}"
export PGPASSWORD="${PGPASSWORD:-postgres}"
export PGDATABASE="${PGDATABASE:-postgres}"
export POSTGRES_TEST_DATABASE_AVAILABLE=1
export POSTGRES_TEST_SLOW=1
export PGSCANNERTMP_ABS_DIR_PREFIX="${RUNTIME_ROOT}/tmp"

pg_log INFO "runner started native_windows=${QA_NATIVE_WINDOWS:-0} source=${UPSTREAM_ROOT} runtime=${RUNTIME_ROOT}"
pg_log INFO "postgres host=${PGHOST} port=${PGPORT} user=${PGUSER} database=${PGDATABASE}"
pg_log INFO "fixture_prefix=${PGSCANNERTMP_ABS_DIR_PREFIX} server_working_directory=${PGSCANNER_SERVER_WORKING_DIRECTORY:-<unset>}"

for required in \
  "${DUCKDB_BIN}" \
  "${STANDARD_RUNNER}" \
  "${FIXTURE_SCRIPT}" \
  "${INSTALL_SCRIPT}" \
  "${INIT_SCRIPT}" \
  "${EXTENSIONS_JSON}" \
  "${PROBE_VALIDATOR}"; do
  if [[ ! -e "${required}" ]]; then
    pg_log ERROR "required test input is missing: ${required}"
    exit 1
  fi
done

ACTUAL_COMMIT="$(git -C "${UPSTREAM_ROOT}" rev-parse HEAD)"
pg_log INFO "upstream commit expected=${EXPECTED_COMMIT} actual=${ACTUAL_COMMIT}"
if [[ "${ACTUAL_COMMIT}" != "${EXPECTED_COMMIT}" ]]; then
  pg_log ERROR "Postgres scanner checkout must be ${EXPECTED_COMMIT}; found ${ACTUAL_COMMIT}"
  exit 1
fi

for attempt in $(seq 1 60); do
  if pg_isready -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" >/dev/null 2>&1; then
    pg_log INFO "PostgreSQL became ready attempt=${attempt}"
    break
  fi
  sleep 1
done

if ! pg_isready -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" >/dev/null 2>&1; then
  pg_log ERROR "PostgreSQL test service did not become ready"
  exit 1
fi

sql_from_file() {
  sed '/^[[:space:]]*--/d; /^[[:space:]]*$/d' "$1" | tr '\n' ' '
}
INSTALL_SQL="$(sql_from_file "${INSTALL_SCRIPT}")"
INIT_SQL="$(sql_from_file "${INIT_SCRIPT}")"

{
  echo "expected_commit=${EXPECTED_COMMIT}"
  echo "actual_commit=${ACTUAL_COMMIT}"
  echo "test_filter=${TEST_FILTER}"
  echo "postgres_host=${PGHOST}"
  echo "postgres_port=${PGPORT}"
  echo "postgres_user=${PGUSER}"
  echo "native_windows=${QA_NATIVE_WINDOWS:-0}"
  echo "fixture_prefix=${PGSCANNERTMP_ABS_DIR_PREFIX}"
  echo "server_working_directory=${PGSCANNER_SERVER_WORKING_DIRECTORY:-}"
} >"${LOG_DIR}/postgres-scanner-info.txt"

pg_log INFO "probing installed extension set"
"${DUCKDB_BIN}" -csv -header -c "${INSTALL_SQL} ${INIT_SQL}
  SELECT extension_name, installed, loaded, extension_version, install_mode, installed_from
  FROM duckdb_extensions()
  ORDER BY extension_name;" | tee "${LOG_DIR}/postgres-scanner-extension.csv"

python3 "${PROBE_VALIDATOR}" \
  "${LOG_DIR}/postgres-scanner-extension.csv" \
  "${EXTENSIONS_JSON}"

python3 - "${LOG_DIR}/postgres-scanner-extension.csv" "${EXPECTED_COMMIT}" <<'PY'
import csv
import sys
from pathlib import Path

rows = list(csv.DictReader(Path(sys.argv[1]).open(encoding="utf-8")))
by_name = {row["extension_name"]: row for row in rows}
row = by_name.get("postgres_scanner")
if not row:
    raise SystemExit("Postgres scanner probe is missing postgres_scanner")
reported_commit = row.get("extension_version", "").lower().removeprefix("v")
expected_commit = sys.argv[2].lower()
if len(reported_commit) < 7 or not expected_commit.startswith(reported_commit):
    raise SystemExit(
        "Postgres scanner source/binary commit mismatch: "
        f"tests use {expected_commit}, binary reports {reported_commit or '<empty>'}"
    )
print(f"Postgres scanner release alignment verified: {expected_commit} -> {reported_commit}")
PY

pg_log INFO "preparing PostgreSQL fixtures from upstream contract"
(
  cd "${UPSTREAM_ROOT}"
  source ./create-postgres-tables.sh
  psql -d postgresscanner -c "SELECT 42"
  psql -d postgresscanner -c "SELECT * FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
) 2>&1 | tee "${LOG_DIR}/services/postgres-fixtures.log"
pg_log INFO "PostgreSQL fixtures prepared successfully"

prepare_windows_server_copy_paths() {
  [[ "${QA_NATIVE_WINDOWS:-0}" == "1" ]] || return 0

  local binary_test="${UPSTREAM_ROOT}/test/sql/misc/postgres_binary.test"
  if [[ ! -f "${binary_test}" ]]; then
    pg_log ERROR "Windows server-side COPY test is missing: ${binary_test}"
    return 1
  fi
  if [[ -z "${PGSCANNER_SERVER_WORKING_DIRECTORY:-}" ]]; then
    pg_log ERROR "PGSCANNER_SERVER_WORKING_DIRECTORY is required for native Windows server-side COPY tests"
    return 1
  fi

  # SQLLogicTest expands __TEST_DIR__ using native Windows separators. The
  # PostgreSQL server runs in Linux, where a backslash is a normal filename
  # character rather than a directory separator. Normalize the final expanded
  # path inside DuckDB SQL before passing it to postgres_execute. Apply this to
  # every matching COPY statement in the file; do not assume a fixed count.
  python3 - "${binary_test}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = "'COPY binary_copy_test FROM ''${PGSCANNER_SERVER_WORKING_DIRECTORY}/__TEST_DIR__/pg_binary.bin'' (FORMAT binary)'"
new = "'COPY binary_copy_test FROM ''' || replace('${PGSCANNER_SERVER_WORKING_DIRECTORY}/__TEST_DIR__/pg_binary.bin', chr(92), '/') || ''' (FORMAT binary)'"
count = text.count(old)
if count == 0:
    raise SystemExit(
        f"{path}: Windows PostgreSQL server-side COPY adaptation anchor was not found"
    )
text = text.replace(old, new)
if old in text:
    raise SystemExit(f"{path}: an unnormalized PostgreSQL server-side COPY path remains")
path.write_text(text, encoding="utf-8")
print(f"Normalized {count} PostgreSQL server-side COPY path expression(s) for Windows")
PY

  pg_log INFO "Windows server-side COPY path bridge prepared file=${binary_test} server_root=${PGSCANNER_SERVER_WORKING_DIRECTORY}"
}

prepare_windows_server_copy_paths

status=0
pg_log INFO "starting SQLLogicTest filter=${TEST_FILTER}"
# The composable service manager owns PostgreSQL 17. The specialized runner
# prepares fixtures and delegates only declarative profile execution.
bash "${STANDARD_RUNNER}" \
  postgres_scanner \
  "${UPSTREAM_ROOT}" || status=$?
pg_log INFO "SQLLogicTest finished exit_code=${status}"

if [[ -f "${UNITTEST_LOG}" ]] && grep -Eq '^require-env (POSTGRES_TEST_DATABASE_AVAILABLE|POSTGRES_TEST_SLOW): [1-9][0-9]*$' "${UNITTEST_LOG}"; then
  pg_log ERROR "mandatory Postgres scanner integration tests were skipped"
  grep -E '^require-env POSTGRES_TEST' "${UNITTEST_LOG}" >&2 || true
  status=1
fi

if [[ -f "${UNITTEST_LOG}" ]]; then
  summary="$(grep -E 'test cases?:' "${UNITTEST_LOG}" | tail -n 1 || true)"
  [[ -z "${summary}" ]] || pg_log INFO "summary=${summary}"
fi

pg_log INFO "runner completed exit_code=${status}"
exit "${status}"
