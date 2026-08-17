#!/usr/bin/env bash
# Composable service lifecycle for DuckDB extension QA.
# Source this file; do not execute it directly.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "service-manager.sh must be sourced" >&2
  exit 2
fi

QA_SERVICE_RUNTIME_ROOT=""
QA_SERVICE_UPSTREAM_ROOT=""
QA_SERVICE_LOG_DIR=""
declare -ag QA_SERVICE_CLEANUPS=()

qa_service_manager_init() {
  QA_SERVICE_RUNTIME_ROOT="${1:?service runtime root is required}"
  QA_SERVICE_UPSTREAM_ROOT="${2:?upstream root is required}"
  QA_SERVICE_LOG_DIR="${3:?service log directory is required}"
  QA_SERVICE_CLEANUPS=()
  mkdir -p "${QA_SERVICE_RUNTIME_ROOT}" "${QA_SERVICE_LOG_DIR}"
}

qa_service_wait_for_port() {
  local port=$1
  local label=$2
  local attempts=${3:-60}
  for _ in $(seq 1 "${attempts}"); do
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

qa_service_rows() {
  local services_file=$1
  python3 - "${services_file}" <<'PY'
import json
import sys
from pathlib import Path
services = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not isinstance(services, list):
    raise SystemExit("services manifest must contain a list")
for item in services:
    fields = [
        item.get("name", "-"),
        item.get("type", "-"),
        item.get("port", "-"),
        item.get("version", "-"),
        item.get("database", "-"),
        item.get("username", "-"),
        str(item.get("auth", False)).lower(),
    ]
    print("|".join(str(value) for value in fields))
PY
}

qa_service_start_python_http() {
  local name=$1
  local port=$2
  local root="${QA_SERVICE_RUNTIME_ROOT}/${name}/root"
  local log="${QA_SERVICE_LOG_DIR}/${name}.log"
  mkdir -p "${root}"
  python3 -m http.server "${port}" \
    --bind 127.0.0.1 \
    --directory "${root}" \
    >"${log}" 2>&1 &
  local pid=$!
  QA_SERVICE_CLEANUPS+=("pid|${name}|${pid}")
  qa_service_wait_for_port "${port}" "Python HTTP service ${name}"
  export PYTHON_HTTP_SERVER_DIR="${root}"
  export PYTHON_HTTP_SERVER_URL="http://127.0.0.1:${port}"
}

qa_service_start_squid() {
  local name=$1
  local port=$2
  local auth=${3:-false}
  local script="${QA_SERVICE_UPSTREAM_ROOT}/scripts/run_squid.sh"
  if [[ ! -x "${script}" ]]; then
    echo "Squid service script is missing: ${script}" >&2
    return 1
  fi
  local log_dir="${QA_SERVICE_LOG_DIR}/${name}"
  local -a args=(--port "${port}" --log_dir "${log_dir}")
  if [[ "${auth}" == "true" ]]; then
    args+=(--auth)
  fi

  sudo systemctl stop squid >/dev/null 2>&1 \
    || sudo service squid stop >/dev/null 2>&1 \
    || true
  sudo rm -f /dev/shm/squid-* >/dev/null 2>&1 || true

  rm -rf "${log_dir}"
  (
    cd "${QA_SERVICE_UPSTREAM_ROOT}"
    ./scripts/run_squid.sh "${args[@]}"
  ) >"${QA_SERVICE_LOG_DIR}/${name}-process.log" 2>&1 &
  local pid=$!
  QA_SERVICE_CLEANUPS+=("pid|${name}|${pid}")
  qa_service_wait_for_port "${port}" "Squid service ${name}"
  export HTTP_PROXY_PUBLIC="127.0.0.1:${port}"
  export HTTP_PROXY_RUNNING=1
  echo "[qa-services] squid-env name=${name} HTTP_PROXY_PUBLIC=${HTTP_PROXY_PUBLIC} HTTP_PROXY_RUNNING=${HTTP_PROXY_RUNNING}" >&2
}

qa_service_start_httpfs_minio() {
  local name=$1
  local compose_file="${QA_SERVICE_UPSTREAM_ROOT}/scripts/minio_s3.yml"
  for required in \
    "${compose_file}" \
    "${QA_SERVICE_UPSTREAM_ROOT}/scripts/generate_presigned_url.sh" \
    "${QA_SERVICE_UPSTREAM_ROOT}/scripts/run_s3_test_server.sh" \
    "${QA_SERVICE_UPSTREAM_ROOT}/scripts/set_s3_test_server_variables.sh"; do
    if [[ ! -e "${required}" ]]; then
      echo "HTTPFS MinIO service input is missing: ${required}" >&2
      return 1
    fi
  done
  if [[ -d "${QA_SERVICE_UPSTREAM_ROOT}/data/secrets" ]]; then
    chmod -R 700 "${QA_SERVICE_UPSTREAM_ROOT}/data/secrets"
  fi
  for host in \
    duckdb-minio.com \
    test-bucket.duckdb-minio.com \
    test-bucket-2.duckdb-minio.com \
    test-bucket-public.duckdb-minio.com; do
    if ! grep -Eq "(^|[[:space:]])${host}([[:space:]]|$)" /etc/hosts; then
      echo "127.0.0.1 ${host}" | sudo tee -a /etc/hosts >/dev/null
    fi
  done
  (
    cd "${QA_SERVICE_UPSTREAM_ROOT}"
    ./scripts/generate_presigned_url.sh
  )
  pushd "${QA_SERVICE_UPSTREAM_ROOT}" >/dev/null
  source ./scripts/run_s3_test_server.sh
  source ./scripts/set_s3_test_server_variables.sh
  popd >/dev/null
  export TEST_PERSISTENT_SECRETS_AVAILABLE=true
  QA_SERVICE_CLEANUPS+=("httpfs-minio|${name}|${compose_file}")
}

qa_service_start_azurite() {
  local name=$1
  local port=$2
  local root="${QA_SERVICE_RUNTIME_ROOT}/${name}"
  local log="${QA_SERVICE_LOG_DIR}/${name}.log"
  local upload_script="${QA_SERVICE_UPSTREAM_ROOT}/scripts/upload_test_files_to_azurite.sh"

  command -v azurite >/dev/null 2>&1 || {
    echo "Azurite executable is missing" >&2
    return 1
  }
  command -v az >/dev/null 2>&1 || {
    echo "Azure CLI executable is missing" >&2
    return 1
  }
  if [[ ! -x "${upload_script}" ]]; then
    echo "Azurite fixture script is missing or not executable: ${upload_script}" >&2
    return 1
  fi

  mkdir -p "${root}"
  azurite \
    --skipApiVersionCheck \
    --location "${root}" \
    --blobHost 127.0.0.1 \
    --blobPort "${port}" \
    >"${log}" 2>&1 &
  local pid=$!
  QA_SERVICE_CLEANUPS+=("pid|${name}|${pid}")
  qa_service_wait_for_port "${port}" "Azurite service ${name}"

  local account="devstoreaccount1"
  local key="Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
  local suffix
  suffix="${USER:-user}/$(TZ=Z date +'%Y%m%dT%H%M%SZ')--$(python3 -c 'import uuid; print(str(uuid.uuid4())[10:17])')"

  export AZURE_STORAGE_ACCOUNT="${account}"
  export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=http;AccountName=${account};AccountKey=${key};BlobEndpoint=http://127.0.0.1:${port}/${account};QueueEndpoint=http://127.0.0.1:10001/${account};TableEndpoint=http://127.0.0.1:10002/${account};"
  export AZ_STORAGE_ACCOUNT="${account}"
  export AZ_DATA_DIR="testing-private"
  export AZ_TEMP_DIR="writes/${suffix}"
  export AZURE_PROTOCOL="az"
  export AZURE_PROVIDER="local"
  export DUCKDB_AZURE_PUBLIC_CONTAINER_AVAILABLE=1

  (
    cd "${QA_SERVICE_UPSTREAM_ROOT}"
    ./scripts/upload_test_files_to_azurite.sh
  ) >>"${log}" 2>&1

  local secret_name
  secret_name="qa_azure_$(printf '%s' "${QA_SERVICE_RUNTIME_ROOT}" | sha256sum | cut -c1-12)"
  duckdb -c "CREATE PERSISTENT SECRET ${secret_name} (TYPE AZURE, CONNECTION_STRING '${AZURE_STORAGE_CONNECTION_STRING}')" \
    >>"${log}" 2>&1
  export ENABLE_DATA_INTEGRITY=1
  export DUCKDB_AZURE_PERSISTENT_SECRET_AVAILABLE=1
}

qa_service_start_unity_catalog_oss() {
  local name=$1
  local port=$2
  local version=$3
  local root="${QA_SERVICE_RUNTIME_ROOT}/${name}"
  local checkout="${root}/unitycatalog"
  local log="${QA_SERVICE_LOG_DIR}/${name}.log"

  if [[ "${port}" != "8080" ]]; then
    echo "The OSS Unity Catalog server currently requires port 8080" >&2
    return 1
  fi
  command -v java >/dev/null 2>&1 || {
    echo "Java is required for the OSS Unity Catalog server" >&2
    return 1
  }
  command -v git >/dev/null 2>&1 || {
    echo "Git is required for the OSS Unity Catalog server" >&2
    return 1
  }

  rm -rf "${root}"
  mkdir -p "${checkout}"
  git -C "${checkout}" init -q
  git -C "${checkout}" remote add origin https://github.com/unitycatalog/unitycatalog.git
  git -C "${checkout}" fetch --depth 1 origin "${version}" >>"${log}" 2>&1
  git -C "${checkout}" checkout --detach FETCH_HEAD >>"${log}" 2>&1
  local actual
  actual="$(git -C "${checkout}" rev-parse HEAD)"
  if [[ "${actual}" != "${version}" ]]; then
    echo "Unity Catalog server checkout must be ${version}; found ${actual}" >&2
    return 1
  fi

  # The official sample catalog stores the UniForm table metadata with an
  # absolute /tmp/marksheet_uniform location. Materialize the bundled fixture
  # exactly as documented by the OSS Unity Catalog project before startup.
  rm -rf /tmp/marksheet_uniform
  cp -R \
    "${checkout}/etc/data/external/unity/default/tables/marksheet_uniform" \
    /tmp/marksheet_uniform

  (
    cd "${checkout}"
    ./build/sbt package
  ) >>"${log}" 2>&1

  (
    cd "${checkout}"
    exec setsid ./bin/start-uc-server
  ) >>"${log}" 2>&1 &
  local pid=$!
  QA_SERVICE_CLEANUPS+=("pgid|${name}|${pid}")
  qa_service_wait_for_port "${port}" "OSS Unity Catalog service ${name}" 180
  export UC_TEST_SERVER_RUNNING=1
  export UNITY_CATALOG_OSS_COMMIT="${actual}"
}

qa_service_start_postgres() {
  local name=$1
  local port=$2
  local version=$3
  local database=$4
  local username=$5
  local password="${PGPASSWORD:-postgres}"
  local battery_slug="${BATTERY_NAME:-battery}"
  battery_slug="${battery_slug//_/-}"
  local service_slug="${name//_/-}"
  local container="qa-${battery_slug}-${service_slug}"
  local battery_runtime_root
  battery_runtime_root="$(dirname "${QA_SERVICE_RUNTIME_ROOT}")"
  container="${container:0:63}"

  # PostgreSQL integration fixtures use server-side COPY with absolute paths.
  # Mount both the upstream checkout and the battery temp directory at the
  # identical paths so the containerized server sees runner-generated files.
  mkdir -p "${battery_runtime_root}/tmp"
  docker rm -f "${container}" >/dev/null 2>&1 || true
  docker run -d \
    --name "${container}" \
    -e "POSTGRES_USER=${username}" \
    -e "POSTGRES_PASSWORD=${password}" \
    -e "POSTGRES_DB=${database}" \
    -p "127.0.0.1:${port}:5432" \
    -v "${QA_SERVICE_UPSTREAM_ROOT}:${QA_SERVICE_UPSTREAM_ROOT}" \
    -v "${battery_runtime_root}/tmp:${battery_runtime_root}/tmp" \
    "postgres:${version}" >/dev/null
  QA_SERVICE_CLEANUPS+=("container|${name}|${container}")

  for _ in $(seq 1 60); do
    if docker exec "${container}" pg_isready -U "${username}" -d "${database}" >/dev/null 2>&1; then
      export PGHOST=127.0.0.1
      export PGPORT="${port}"
      export PGUSER="${username}"
      export PGPASSWORD="${password}"
      export PGDATABASE="${database}"
      export PGSSLMODE=disable
      export QA_POSTGRES_CONTAINER="${container}"
      return 0
    fi
    sleep 1
  done
  echo "PostgreSQL service ${name} did not become ready" >&2
  return 1
}

qa_service_start_sqlserver() {
  local name=$1
  local port=$2
  local version=$3
  local database=$4
  local username=$5
  local password="${MSSQL_TEST_PASS:-TestPassword1}"
  local compose_file="${QA_SERVICE_UPSTREAM_ROOT}/docker/docker-compose.yml"
  if [[ ! -f "${compose_file}" ]]; then
    echo "SQL Server compose file is missing: ${compose_file}" >&2
    return 1
  fi
  local battery_slug="${BATTERY_NAME:-battery}"
  battery_slug="${battery_slug//_/-}"
  local project="qa-${battery_slug}-${name//_/-}"

  export MSSQL_TEST_HOST=localhost
  export MSSQL_TEST_PORT="${port}"
  export MSSQL_TEST_USER="${username}"
  export MSSQL_TEST_PASS="${password}"
  export MSSQL_TEST_DB="${database}"
  export MSSQL_TEST_DSN="Server=${MSSQL_TEST_HOST},${MSSQL_TEST_PORT};Database=${MSSQL_TEST_DB};User Id=${MSSQL_TEST_USER};Password=${MSSQL_TEST_PASS}"
  export MSSQL_TEST_URI="mssql://${MSSQL_TEST_USER}:${MSSQL_TEST_PASS}@${MSSQL_TEST_HOST}:${MSSQL_TEST_PORT}/${MSSQL_TEST_DB}"
  export MSSQL_TESTDB_DSN="Server=${MSSQL_TEST_HOST},${MSSQL_TEST_PORT};Database=TestDB;User Id=${MSSQL_TEST_USER};Password=${MSSQL_TEST_PASS}"
  export MSSQL_TESTDB_URI="mssql://${MSSQL_TEST_USER}:${MSSQL_TEST_PASS}@${MSSQL_TEST_HOST}:${MSSQL_TEST_PORT}/TestDB"
  export MSSQL_TEST_SERVER="${MSSQL_TEST_DSN}"
  export MSSQL_TEST_CONNECTION_STRING="${MSSQL_TEST_DSN}"

  cat >"${QA_SERVICE_UPSTREAM_ROOT}/.env" <<EOF
MSSQL_TEST_HOST=${MSSQL_TEST_HOST}
MSSQL_TEST_PORT=${MSSQL_TEST_PORT}
MSSQL_TEST_USER=${MSSQL_TEST_USER}
MSSQL_TEST_PASS=${MSSQL_TEST_PASS}
MSSQL_TEST_DB=${MSSQL_TEST_DB}
EOF

  docker compose -f "${compose_file}" -p "${project}" up -d sqlserver
  local container
  container="$(docker compose -f "${compose_file}" -p "${project}" ps -q sqlserver)"
  if [[ -z "${container}" ]]; then
    echo "SQL Server service ${name} did not create a container" >&2
    return 1
  fi
  QA_SERVICE_CLEANUPS+=("compose|${name}|${compose_file}|${project}")
  for _ in $(seq 1 60); do
    if docker exec "${container}" /opt/mssql-tools18/bin/sqlcmd \
        -S localhost -U "${username}" -P "${password}" -C \
        -Q 'SELECT 1' >/dev/null 2>&1; then
      export SQLSERVER_ID="${container}"
      export MSSQL_COMPOSE_FILE="${compose_file}"
      export MSSQL_COMPOSE_PROJECT="${project}"
      return 0
    fi
    sleep 2
  done
  echo "SQL Server service ${name} did not become ready" >&2
  return 1
}

qa_service_start_file() {
  local services_file=$1
  if [[ ! -f "${services_file}" ]]; then
    echo "Services manifest is missing: ${services_file}" >&2
    return 1
  fi

  # Materialize the manifest before starting any service. Service startup can
  # invoke arbitrary child processes; none of them must be able to consume the
  # stream that contains the remaining service definitions.
  local -a service_rows=()
  mapfile -t service_rows < <(qa_service_rows "${services_file}")
  echo "[qa-services] manifest=${services_file} count=${#service_rows[@]}" >&2

  local row name service_type port version database username auth
  for row in "${service_rows[@]}"; do
    IFS='|' read -r name service_type port version database username auth <<<"${row}"
    [[ -n "${name}" ]] || continue
    echo "[qa-services] start name=${name} type=${service_type} port=${port}" >&2
    case "${service_type}" in
      python-http)
        qa_service_start_python_http "${name}" "${port}"
        ;;
      squid)
        qa_service_start_squid "${name}" "${port}" "${auth}"
        ;;
      httpfs-minio)
        qa_service_start_httpfs_minio "${name}"
        ;;
      azurite)
        qa_service_start_azurite "${name}" "${port}"
        ;;
      unity-catalog-oss)
        qa_service_start_unity_catalog_oss "${name}" "${port}" "${version}"
        ;;
      postgres)
        qa_service_start_postgres \
          "${name}" "${port}" "${version}" "${database}" "${username:-postgres}"
        ;;
      sqlserver)
        qa_service_start_sqlserver \
          "${name}" "${port}" "${version}" "${database}" "${username:-sa}"
        ;;
      *)
        echo "Unsupported service type: ${service_type}" >&2
        return 2
        ;;
    esac
    echo "[qa-services] ready name=${name} type=${service_type}" >&2
  done
}

qa_prerequisite_check_file() {
  local prerequisites_file=$1
  python3 - "${prerequisites_file}" <<'PY' | while IFS= read -r prerequisite; do
import json
import sys
from pathlib import Path
items = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not isinstance(items, list):
    raise SystemExit("prerequisites manifest must contain a list")
for item in items:
    print(item["type"])
PY
    case "${prerequisite}" in
      google-bigquery)
        for variable_name in GOOGLE_APPLICATION_CREDENTIALS BQ_TEST_PROJECT BQ_TEST_DATASET; do
          if [[ -z "${!variable_name:-}" ]]; then
            echo "Google BigQuery prerequisite requires ${variable_name}" >&2
            return 1
          fi
        done
        ;;
      external-cloud-account)
        ;;
      *)
        echo "Unsupported prerequisite: ${prerequisite}" >&2
        return 2
        ;;
    esac
  done
}

qa_service_stop_all() {
  local index action kind name value extra
  for ((index=${#QA_SERVICE_CLEANUPS[@]}-1; index>=0; index--)); do
    action="${QA_SERVICE_CLEANUPS[index]}"
    IFS='|' read -r kind name value extra <<<"${action}"
    case "${kind}" in
      pid)
        if [[ -n "${value}" ]] && kill -0 "${value}" 2>/dev/null; then
          kill "${value}" || true
          wait "${value}" 2>/dev/null || true
        fi
        ;;
      pgid)
        if [[ -n "${value}" ]]; then
          kill -TERM -- "-${value}" >/dev/null 2>&1 || true
          wait "${value}" 2>/dev/null || true
        fi
        ;;
      httpfs-minio)
        (
          cd "${QA_SERVICE_UPSTREAM_ROOT}"
          docker compose -f "${value}" -p duckdb-minio logs --no-color
        ) >"${QA_SERVICE_LOG_DIR}/${name}.log" 2>&1 || true
        (
          cd "${QA_SERVICE_UPSTREAM_ROOT}"
          docker compose -f "${value}" -p duckdb-minio down --volumes --remove-orphans
        ) >>"${QA_SERVICE_LOG_DIR}/${name}.log" 2>&1 || true
        ;;
      container)
        docker logs "${value}" >"${QA_SERVICE_LOG_DIR}/${name}.log" 2>&1 || true
        docker rm -f "${value}" >/dev/null 2>&1 || true
        ;;
      compose)
        docker compose -f "${value}" -p "${extra}" logs --no-color \
          >"${QA_SERVICE_LOG_DIR}/${name}.log" 2>&1 || true
        docker compose -f "${value}" -p "${extra}" down --volumes --remove-orphans \
          >>"${QA_SERVICE_LOG_DIR}/${name}.log" 2>&1 || true
        ;;
    esac
  done
  QA_SERVICE_CLEANUPS=()
}
