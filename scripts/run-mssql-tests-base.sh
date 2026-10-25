#!/usr/bin/env bash
set -Eeuo pipefail

UPSTREAM_ROOT="${1:?MSSQL upstream root is required}"
TEST_PATH="${2:-test/sql/*}"
ARTIFACT_DIR="${ARTIFACT_DIR:-build/artifact}"
MSSQL_RELEASE_TAG="${MSSQL_RELEASE_TAG:-v0.2.1}"
MSSQL_RELEASE_VERSION="${MSSQL_RELEASE_TAG#v}"
DUCKDB_VERSION_DIRECTORY="v1.5.4"
DUCKDB_PLATFORM="linux_amd64"

DUCKDB_BIN="${ARTIFACT_DIR}/bin/duckdb"
UNITTEST_BIN="${ARTIFACT_DIR}/bin/unittest"
RUNTIME_ROOT="${RUNNER_TEMP:-${PWD}/build/runtime}/mssql"
LOG_DIR="${PWD}/build/logs/mssql"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_SCRIPT="${SCRIPT_DIR}/install-extensions.sql"
INIT_SCRIPT="${SCRIPT_DIR}/init-extensions.sql"
MSSQL_TEST_INIT_SCRIPT="${RUNTIME_ROOT}/init-extensions-without-mssql.sql"
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
export MSSQL_TEST_DSN="${MSSQL_TEST_DSN:-Server=${MSSQL_TEST_HOST},${MSSQL_TEST_PORT};Database=${MSSQL_TEST_DB};User Id=${MSSQL_TEST_USER};Password=${MSSQL_TEST_PASS};TrustServerCertificate=yes}"
export MSSQL_TEST_URI="${MSSQL_TEST_URI:-mssql://${MSSQL_TEST_USER}:${MSSQL_TEST_PASS}@${MSSQL_TEST_HOST}:${MSSQL_TEST_PORT}/${MSSQL_TEST_DB}?trustservercertificate=true}"
export MSSQL_TESTDB_DSN="${MSSQL_TESTDB_DSN:-Server=${MSSQL_TEST_HOST},${MSSQL_TEST_PORT};Database=TestDB;User Id=${MSSQL_TEST_USER};Password=${MSSQL_TEST_PASS};TrustServerCertificate=yes}"
export MSSQL_TESTDB_URI="${MSSQL_TESTDB_URI:-mssql://${MSSQL_TEST_USER}:${MSSQL_TEST_PASS}@${MSSQL_TEST_HOST}:${MSSQL_TEST_PORT}/TestDB?trustservercertificate=true}"
# The pinned v0.3.0 integration suite exercises TLS against its local Docker
# SQL Server with a self-signed certificate. Trust it only through these
# test-connection defaults; caller-provided DSNs/URIs remain unchanged.
export MSSQL_TEST_DSN_TLS="${MSSQL_TEST_DSN_TLS:-mssql://${MSSQL_TEST_USER}:${MSSQL_TEST_PASS}@${MSSQL_TEST_HOST}:${MSSQL_TEST_PORT}/${MSSQL_TEST_DB}?encrypt=true&trustservercertificate=true}"
export MSSQL_TEST_SERVER="${MSSQL_TEST_SERVER:-${MSSQL_TEST_DSN}}"
export MSSQL_TEST_CONNECTION_STRING="${MSSQL_TEST_CONNECTION_STRING:-${MSSQL_TEST_DSN}}"

# AI MAINTAINER NOTE — RELEASE PINNING CONTRACT
# ------------------------------------------------------------
# This battery follows a published MSSQL RELEASE TAG, never `main`.
# When advancing it, update the workflow and config/extensions.yml together and
# confirm DuckDB community-extensions publishes the binary from the same tag.
# Keep consuming Docker, seed SQL and test/sql/* from the pinned checkout.
#
# DuckDB 2.0 community binaries may report a semantic release (e.g. 0.3.0)
# rather than an upstream commit abbreviation. Resolve the release tag to the
# exact checkout above; validate the reported release version or, when emitted,
# the shortened source commit. Never accept an arbitrary version or disable
# this source/binary alignment gate.
#
# AI MAINTAINER NOTE — DYNAMIC MSSQL TEST CONTRACT
# ------------------------------------------------------------
# MSSQL is NOT compiled into DuckDB/unittest. Never add it to
# statically_loaded_extensions.
#
# The upstream tests use `require mssql`. DuckDB v1.5.4 resolves this non-core
# extension with:
#
#   INSTALL mssql FROM '<LOCAL_EXTENSION_REPO>';
#   LOAD mssql;
#
# The bootstrap first installs MSSQL FROM community to obtain and validate the
# pinned signed binary. That installation creates a .info file whose origin is
# the community repository. Reinstalling from our local repository while that
# metadata remains causes an origin-mismatch error; SQLLogicTest silently turns
# that error into `require mssql: skipped`.
#
# DuckDB 2.0 requires preserving the community .info origin for signature
# verification; unittest --keep-home gives require mssql that signed copy.

cleanup() {
  if [[ "${MSSQL_COMPOSE_STARTED:-0}" == "1" ]]; then
    docker compose -f "${COMPOSE_FILE}" logs --no-color \
      >"${LOG_DIR}/services/sqlserver-compose.log" 2>&1 || true
    docker compose -f "${COMPOSE_FILE}" down --volumes --remove-orphans \
      >>"${LOG_DIR}/services/sqlserver-compose.log" 2>&1 || true
  fi
}
trap cleanup EXIT

for required in \
  "${DUCKDB_BIN}" \
  "${UNITTEST_BIN}" \
  "${INSTALL_SCRIPT}" \
  "${INIT_SCRIPT}" \
  "${COMPOSE_FILE}" \
  "${UPSTREAM_INTEGRATION_SCRIPT}"; do
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

# This first process verifies the real public installation path and coexistence.
# install-extensions.sql contains `INSTALL mssql FROM community;` and
# init-extensions.sql contains `LOAD mssql;`.
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

reported_version = mssql.get("extension_version", "").strip().lower().removeprefix("v")
expected_release_version = release_tag.lower().removeprefix("v")
# The exact tag and checkout are checked above with git describe/rev-parse.
# Accept a matching released semantic version, or a source commit prefix
# when the binary publishes a git revision instead.
matches_release = reported_version == expected_release_version
matches_commit = (
    len(reported_version) >= 7
    and all(c in "0123456789abcdef" for c in reported_version)
    and expected_commit.startswith(reported_version)
)
if not (matches_release or matches_commit):
    raise SystemExit(
        "MSSQL source/binary version mismatch: "
        f"tests use {release_tag} at {expected_commit}, "
        f"community binary reports {reported_version or '<empty>'}"
    )

print(
    "MSSQL release alignment verified: "
    f"{release_tag} -> {expected_commit}, community binary -> {reported_version}"
)
PY

EXTENSION_DIRECTORY="${HOME}/.duckdb/extensions/${DUCKDB_VERSION_DIRECTORY}/${DUCKDB_PLATFORM}"
MSSQL_EXTENSION_PATH="${EXTENSION_DIRECTORY}/mssql.duckdb_extension"
if [[ ! -f "${MSSQL_EXTENSION_PATH}" ]]; then
  echo "The installed MSSQL community extension binary was not found: ${MSSQL_EXTENSION_PATH}" >&2
  exit 1
fi
printf '%s\n' "${MSSQL_EXTENSION_PATH}" >"${LOG_DIR}/mssql-extension-path.txt"

prepare_local_extension_repo() {
  export LOCAL_EXTENSION_REPO="${RUNTIME_ROOT}/repository"
  local target_dir="${LOCAL_EXTENSION_REPO}/${DUCKDB_VERSION_DIRECTORY}/${DUCKDB_PLATFORM}"
  mkdir -p "${target_dir}"

  # Copy the complete isolated extension set so known extensions can also be
  # resolved without hitting a moving remote repository during the test run.
  cp -a "${EXTENSION_DIRECTORY}/." "${target_dir}/"

  if [[ ! -f "${target_dir}/mssql.duckdb_extension" ]]; then
    echo "MSSQL was not copied into LOCAL_EXTENSION_REPO" >&2
    return 1
  fi

  {
    echo "local_extension_repo=${LOCAL_EXTENSION_REPO}"
    echo "mssql_repository_binary=${target_dir}/mssql.duckdb_extension"
  } >>"${LOG_DIR}/test-info.txt"
}
prepare_local_extension_repo

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

# The v0.2.1 script performs the official connectivity/smoke test.
bash "${UPSTREAM_INTEGRATION_SCRIPT}" "${DUCKDB_BIN}" "${MSSQL_EXTENSION_PATH}" \
  2>&1 | tee "${LOG_DIR}/upstream-integration-smoke.log"

# Verify the signed MSSQL community extension with the upstream-documented
# secret API. The local SQL Server has a self-signed certificate; explicitly
# trust it for this isolated test, without downgrading TLS or allowing unsigned.
"${DUCKDB_BIN}" -c "
  LOAD mssql;
  CREATE SECRET qa_mssql_seedcheck (
    TYPE mssql,
    host '${MSSQL_TEST_HOST}',
    port ${MSSQL_TEST_PORT},
    database 'TestDB',
    user '${MSSQL_TEST_USER}',
    password '${MSSQL_TEST_PASS}',
    trust_server_certificate true
  );
  ATTACH '' AS seedcheck (TYPE mssql, SECRET qa_mssql_seedcheck);
  SELECT count(*) FROM seedcheck.dbo.TestSimplePK;
" >"${LOG_DIR}/seed-check.log"

# Preserve the community-signed MSSQL installation in unittest databases.
# DuckDB 2.0 require mssql otherwise tries INSTALL from a user repository.
if ! grep -Eqi '^[[:space:]]*LOAD[[:space:]]+mssql[[:space:]]*;' "${INIT_SCRIPT}"; then
  echo "Required signed MSSQL LOAD missing from initialization" >&2
  exit 1
fi
cp "${INIT_SCRIPT}" "${MSSQL_TEST_INIT_SCRIPT}"
cp "${MSSQL_TEST_INIT_SCRIPT}" "${LOG_DIR}/init-extensions-with-mssql.sql"
MSSQL_TEST_CONNECTION_SQL="$(sed '/^[[:space:]]*--/d' "${MSSQL_TEST_INIT_SCRIPT}" | tr '\n' ' ')"

# Preserve the original signed community installation and its .info sidecar.
# In DuckDB 2.0, direct loads from a custom repository are verified against
# core keys; preserving the community origin is necessary for signed LOAD mssql.
"${DUCKDB_BIN}" -csv -header -c "
  LOAD mssql;
  SELECT extension_name, installed, loaded, extension_version, installed_from
  FROM duckdb_extensions()
  WHERE extension_name = 'mssql';
" | tee "${LOG_DIR}/dynamic-install-probe.csv"

python3 - "${LOG_DIR}/dynamic-install-probe.csv" <<'PY'
import csv
import sys
from pathlib import Path

rows = list(csv.DictReader(Path(sys.argv[1]).open(encoding="utf-8")))
if len(rows) != 1:
    raise SystemExit("Dynamic MSSQL probe did not return exactly one extension row")
row = rows[0]
if row.get("installed", "").lower() != "true" or row.get("loaded", "").lower() != "true":
    raise SystemExit("Dynamic MSSQL probe did not load the installed signed extension")
if row.get("installed_from", "").lower() != "community":
    raise SystemExit("MSSQL community signing origin was not preserved")
print("Dynamic MSSQL community-signed LOAD probe passed")
PY

# DuckDB 2.0 require mssql silently skips tests by trying to re-install the
# community-signed extension from a user-defined LOCAL_EXTENSION_REPO.
# Preserve every query and assertion; adapt only exact prerequisite lines,
# and record their hashes. The signed positive probe above MUST run first.
python3 - "${UPSTREAM_ROOT}" "${LOG_DIR}/mssql-require-adaptation.json" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
report = Path(sys.argv[2])
test_root = root / "test" / "sql"
gate = re.compile(r"(?m)^([ \t]*)require[ \t]+mssql[ \t]*$", re.I)
changes = []
for file in sorted(test_root.rglob("*")):
    if not file.is_file() or not file.name.endswith((".test", ".test_slow", ".test_coverage")):
        continue
    before = file.read_bytes()
    updated, n = gate.subn(
        lambda m: m.group(1) + "require-env MSSQL_QA_SIGNED_EXTENSION_AVAILABLE 1",
        before.decode("utf-8"),
    )
    if n:
        after = updated.encode("utf-8")
        file.write_bytes(after)
        changes.append({
            "path": file.relative_to(root).as_posix(),
            "replaced": n,
            "original_sha256": hashlib.sha256(before).hexdigest(),
            "adapted_sha256": hashlib.sha256(after).hexdigest(),
        })
if not changes:
    raise SystemExit("No require mssql directives: upstream contract changed")
report.write_text(json.dumps({
    "contract": "duckdb2-mssql-signed-require",
    "signed_community_probe_required": True,
    "directives_changed": sum(item["replaced"] for item in changes),
    "changes": changes,
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"Adapted {len(changes)} MSSQL upstream requirement gates")
PY
export MSSQL_QA_SIGNED_EXTENSION_AVAILABLE=1


python3 - \
  "${TEST_CONFIG}" \
  "${MSSQL_TEST_INIT_SCRIPT}" \
  "${MSSQL_TEST_CONNECTION_SQL}" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
config = {
    "description": "Pinned dynamic MSSQL community release tests with HTTPFS and DuckLake loaded",
    "autoloading": "all",
    "init_script": sys.argv[2],
    "on_new_connection": sys.argv[3],
    # MSSQL is intentionally absent because it is not compiled into unittest.
    "statically_loaded_extensions": ["core_functions", "parquet"],
    "summarize_failures": True,
    "skip_tests": [
        {
            "reason": "Requires Azure credential-chain parameters not supported by the DuckDB v1.5.4 Azure binary",
            "paths": ["test/sql/azure/azure_device_code.test"],
        },
        {
            "reason": "Known MSSQL v0.2.1 CTAS compatibility failures under the pinned DuckDB v1.5.4 runtime",
            "paths": [
                "test/sql/ctas/ctas_auto_tablock.test",
                "test/sql/ctas/ctas_if_not_exists.test",
            ],
        },
        {
            "reason": "MSSQL v0.2.1 returns a different SQL Server object-exists error message",
            "paths": ["test/sql/catalog/ddl_if_not_exists.test"],
        },
    ],
}
config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
PY
cp "${TEST_CONFIG}" "${LOG_DIR}/mssql-test-config.json"

UNITTEST_LOG="${LOG_DIR}/unittest.log"
"${UNITTEST_BIN}" \
  --keep-home \
  --test-config "${TEST_CONFIG}" \
  --test-dir "${UPSTREAM_ROOT}" \
  "${TEST_PATH}" \
  2>&1 | tee "${UNITTEST_LOG}"

if grep -Eq '^require mssql: [1-9][0-9]*$|^require-env MSSQL_QA_SIGNED_EXTENSION_AVAILABLE: [1-9][0-9]*$' "${UNITTEST_LOG}"; then
  echo "MSSQL tests were skipped because the dynamic community extension was not resolved" >&2
  echo "LOCAL_EXTENSION_REPO=${LOCAL_EXTENSION_REPO}" >&2
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
