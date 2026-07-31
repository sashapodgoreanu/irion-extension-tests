#!/usr/bin/env bash
set -Eeuo pipefail

ACTION="${1:?action is required}"
UPSTREAM_ROOT="${2:?upstream root is required}"
RUNTIME_ROOT="${3:?runtime root is required}"
LOG_DIR="${4:?log directory is required}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${RUNTIME_ROOT}/iceberg-local"
ENV_FILE="${RUNTIME_ROOT}/iceberg-local.env"
CONTRACT_FILE="${LOG_DIR}/iceberg-local-contract.txt"
COMPOSE_FILE="${UPSTREAM_ROOT}/scripts/docker-compose.yml"
VENV_ROOT="${UPSTREAM_ROOT}/.venv-spark4"
MITM_LOG="${UPSTREAM_ROOT}/mitmproxy.log"
FILTER_LOG_VERIFIER="${SCRIPT_DIR}/verify-iceberg-filter-logging.py"
STALE_FILTER_LOG_TEST="${UPSTREAM_ROOT}/test/sql/local/test_reading_partitioned_table_with_bad_stats.test"
REGULAR_PROXY_PID_FILE="${STATE_DIR}/mitmproxy-regular.pid"
REFRESH_PROXY_PID_FILE="${STATE_DIR}/mitmproxy-refresh.pid"

mkdir -p "${STATE_DIR}" "${LOG_DIR}"

stop_pid_file() {
  local pid_file=$1
  if [[ ! -f "${pid_file}" ]]; then
    return 0
  fi
  local pid
  pid="$(cat "${pid_file}")"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1; then
    kill "${pid}" >/dev/null 2>&1 || true
    for _ in $(seq 1 20); do
      kill -0 "${pid}" >/dev/null 2>&1 || break
      sleep 0.25
    done
    kill -KILL "${pid}" >/dev/null 2>&1 || true
  fi
  rm -f "${pid_file}"
}

stop_fixture() {
  stop_pid_file "${REFRESH_PROXY_PID_FILE}"
  stop_pid_file "${REGULAR_PROXY_PID_FILE}"
  if [[ -f "${MITM_LOG}" ]]; then
    cp "${MITM_LOG}" "${LOG_DIR}/iceberg-mitmproxy.log" || true
  fi
  if [[ -f "${COMPOSE_FILE}" ]]; then
    (
      cd "${UPSTREAM_ROOT}/scripts"
      docker compose down --volumes --remove-orphans
    ) >>"${LOG_DIR}/iceberg-fixture-stop.log" 2>&1 || true
  fi
  rm -f "${ENV_FILE}"
}

if [[ "${ACTION}" == "stop" ]]; then
  stop_fixture
  exit 0
fi
if [[ "${ACTION}" != "start" ]]; then
  echo "Unsupported Iceberg preparation action: ${ACTION}" >&2
  exit 2
fi

stop_fixture
rm -f "${MITM_LOG}"

for command_name in docker make python3 curl java grep awk sed sudo duckdb; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Iceberg local test preparation requires ${command_name}" >&2
    exit 1
  }
done

: "${DUCKDB_VERSION:?DuckDB version is required for the Iceberg local repository}"
: "${LOCAL_EXTENSION_REPO:?Local extension repository is required for Iceberg tests}"

for required in \
  "${UPSTREAM_ROOT}/Makefile" \
  "${UPSTREAM_ROOT}/make/catalogs/fixture.mk" \
  "${UPSTREAM_ROOT}/scripts/docker-compose.yml" \
  "${UPSTREAM_ROOT}/scripts/requirements.txt" \
  "${UPSTREAM_ROOT}/scripts/envs/fixture.env" \
  "${UPSTREAM_ROOT}/scripts/vended_credentials_refresh_proxy.py" \
  "${UPSTREAM_ROOT}/test/configs/fixture.json" \
  "${FILTER_LOG_VERIFIER}" \
  "${STALE_FILTER_LOG_TEST}"; do
  if [[ ! -f "${required}" ]]; then
    echo "Iceberg upstream contract input is missing: ${required}" >&2
    exit 1
  fi
done

# Keep the reusable-workflow targets as drift contracts. The adapter starts the
# fixture once and runs both generators without invoking a second fixture target:
# restarting between them would clean bind-mounted MinIO files owned by root.
for target in fixture-data-local fixture-data fixture fixture-stop; do
  grep -Eq "^${target}:" "${UPSTREAM_ROOT}/make/catalogs/fixture.mk" || {
    echo "Iceberg upstream fixture Makefile no longer exposes ${target}" >&2
    exit 1
  }
done

docker version >/dev/null
docker compose version >/dev/null

if [[ -n "${JAVA_HOME_21_X64:-}" && -x "${JAVA_HOME_21_X64}/bin/java" ]]; then
  export JAVA_HOME="${JAVA_HOME_21_X64}"
elif [[ -n "${JAVA_HOME:-}" && -x "${JAVA_HOME}/bin/java" ]]; then
  export JAVA_HOME
else
  JAVA_HOME="$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")"
  export JAVA_HOME
fi
export PATH="${JAVA_HOME}/bin:${PATH}"

JAVA_MAJOR="$(java -version 2>&1 | sed -n '1s/.*version "\([0-9][0-9]*\).*/\1/p')"
if [[ -z "${JAVA_MAJOR}" || "${JAVA_MAJOR}" -lt 21 ]]; then
  echo "Iceberg fixture generation requires Java 21 or newer; found ${JAVA_MAJOR:-unknown}" >&2
  exit 1
fi

# Three upstream Fixture tests use JSON functions without declaring `require
# json`. The statically linked upstream runner has JSON available implicitly;
# the shared dynamic runtime must materialize it in the local repository.
duckdb -c "INSTALL json;" \
  2>&1 | tee "${LOG_DIR}/iceberg-json-install.log"
JSON_SOURCE_DIR="${HOME}/.duckdb/extensions/${DUCKDB_VERSION}/linux_amd64"
JSON_REPOSITORY_DIR="${LOCAL_EXTENSION_REPO}/${DUCKDB_VERSION}/linux_amd64"
mkdir -p "${JSON_REPOSITORY_DIR}"
mapfile -t JSON_FILES < <(find "${JSON_SOURCE_DIR}" -maxdepth 1 -type f -name 'json*' -print)
if [[ "${#JSON_FILES[@]}" -eq 0 ]]; then
  echo "DuckDB installed JSON but no JSON extension files were found in ${JSON_SOURCE_DIR}" >&2
  exit 1
fi
cp -a "${JSON_FILES[@]}" "${JSON_REPOSITORY_DIR}/"

rm -rf "${VENV_ROOT}"
python3 -m venv "${VENV_ROOT}"
# shellcheck disable=SC1091
source "${VENV_ROOT}/bin/activate"
python3 -m pip install --disable-pip-version-check \
  -r "${UPSTREAM_ROOT}/scripts/requirements.txt" \
  2>&1 | tee "${LOG_DIR}/iceberg-python-requirements.log"

# Clean only REST-owned outputs before containers start. Once MinIO is running,
# its bind-mounted xl.meta files can be root-owned and must not be removed by the
# host runner. Spark-local intermediates are preserved throughout both generators.
sudo rm -rf \
  "${UPSTREAM_ROOT}/data/generated/iceberg/spark-rest" \
  "${UPSTREAM_ROOT}/data/generated/intermediates/spark-rest"
mkdir -p \
  "${UPSTREAM_ROOT}/data/generated/iceberg/spark-rest" \
  "${UPSTREAM_ROOT}/data/generated/intermediates/spark-rest"

wait_for_port() {
  local port=$1
  local label=$2
  for _ in $(seq 1 120); do
    if python3 - "${port}" <<'PY'
import socket
import sys
try:
    with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=1):
        pass
except OSError:
    raise SystemExit(1)
PY
    then
      return 0
    fi
    sleep 1
  done
  echo "${label} did not become ready on port ${port}" >&2
  return 1
}

# Both upstream fixture-data-local and fixture-data depend on the running REST
# catalog and load fixture.env. Start REST/MinIO first, then run both generators
# against the same fixture without restarting or cleaning it in between.
make -C "${UPSTREAM_ROOT}" fixture \
  2>&1 | tee "${LOG_DIR}/iceberg-fixture-start.log"

wait_for_port 8181 "Iceberg REST fixture"
wait_for_port 9000 "Iceberg fixture MinIO"

(
  cd "${UPSTREAM_ROOT}"
  set -a
  # shellcheck disable=SC1091
  source ./scripts/envs/fixture.env
  set +a
  python3 -m scripts.data_generators.generate_data local
) 2>&1 | tee "${LOG_DIR}/iceberg-fixture-data-local.log"

(
  cd "${UPSTREAM_ROOT}"
  set -a
  # shellcheck disable=SC1091
  source ./scripts/envs/fixture.env
  set +a
  python3 -m scripts.data_generators.generate_data spark-rest
) 2>&1 | tee "${LOG_DIR}/iceberg-fixture-data-rest.log"

MITMDUMP="${VENV_ROOT}/bin/mitmdump"
if [[ ! -x "${MITMDUMP}" ]]; then
  echo "Iceberg fixture virtual environment did not install mitmdump: ${MITMDUMP}" >&2
  exit 1
fi

# Upstream fixture tests read mitmproxy.log relative to the Iceberg checkout.
nohup "${MITMDUMP}" --mode regular@8878 --flow-detail 2 \
  >"${MITM_LOG}" 2>&1 &
echo $! >"${REGULAR_PROXY_PID_FILE}"
wait_for_port 8878 "Iceberg HTTP proxy"

nohup "${MITMDUMP}" --mode regular@19133 \
  -s "${UPSTREAM_ROOT}/scripts/vended_credentials_refresh_proxy.py" \
  --flow-detail 2 \
  >"${LOG_DIR}/iceberg-vended-credentials-proxy.log" 2>&1 &
echo $! >"${REFRESH_PROXY_PID_FILE}"
wait_for_port 19133 "Iceberg vended-credential refresh proxy"

for _ in $(seq 1 60); do
  if curl --fail --silent --show-error \
      --proxy http://127.0.0.1:19133 \
      http://127.0.0.1:8181/v1/config >/dev/null; then
    break
  fi
  sleep 1
done
curl --fail --silent --show-error \
  --proxy http://127.0.0.1:19133 \
  http://127.0.0.1:8181/v1/config >/dev/null

if ! find "${UPSTREAM_ROOT}/data/generated" -type f -print -quit | grep -q .; then
  echo "Iceberg upstream data generation produced no fixture files" >&2
  exit 1
fi

# The selected upstream commit emits detailed pruning diagnostics but its SQL
# expectation still contains the older abbreviated messages. Execute a strict
# replacement verifier against the same fixture, then remove only that stale
# assertion file from discovery so the suite is not failed by its own drift.
python3 "${FILTER_LOG_VERIFIER}" "$(command -v duckdb)" "${UPSTREAM_ROOT}" \
  2>&1 | tee "${LOG_DIR}/iceberg-filter-logging-smoke.log"
rm "${STALE_FILTER_LOG_TEST}"

cat >"${ENV_FILE}" <<EOF
export DUCKDB_ICEBERG_HAVE_GENERATED_DATA=1
export FIXTURE_SERVER_AVAILABLE=1
export HTTP_PROXY_PUBLIC=http://localhost:8878
export VENDED_CREDENTIAL_REFRESH_PROXY=http://127.0.0.1:19133
export EQUALITY_DELETE_WRITES_ENABLED=0
export ICEBERG_LOCAL_FIXTURE_PREPARED=1
EOF

{
  echo "fixture_compose=${COMPOSE_FILE}"
  echo "fixture_image=$(awk '/^[[:space:]]+image: apache\/iceberg-rest-fixture:/{print $2; exit}' "${COMPOSE_FILE}")"
  echo "minio_image=$(awk '/^[[:space:]]+image: minio\/minio/{print $2; exit}' "${COMPOSE_FILE}")"
  echo "java_home=${JAVA_HOME}"
  echo "java_version=$(java -version 2>&1 | head -n 1)"
  echo "python_version=$(python3 --version 2>&1)"
  echo "generated_files=$(find "${UPSTREAM_ROOT}/data/generated" -type f | wc -l | tr -d ' ')"
  echo "json_repository_files=${#JSON_FILES[@]}"
  echo "filter_logging_replacement=verify-iceberg-filter-logging.py"
} >"${CONTRACT_FILE}"

echo "Prepared Iceberg local generated data and REST fixture: ${ENV_FILE}"
