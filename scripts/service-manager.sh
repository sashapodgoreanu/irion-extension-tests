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
  local script="${QA_SERVICE_UPSTREAM_ROOT}/scripts/run_squid.sh"
  if [[ ! -x "${script}" ]]; then
    echo "Squid service script is missing: ${script}" >&2
    return 1
  fi
  # The pinned upstream script owns creation of its log directory and uses
  # plain `mkdir`, so the path must not exist before it starts.
  rm -rf "${QA_SERVICE_LOG_DIR}/${name}"
  (
    cd "${QA_SERVICE_UPSTREAM_ROOT}"
    ./scripts/run_squid.sh \
      --port "${port}" \
      --log_dir "${QA_SERVICE_LOG_DIR}/${name}"
  ) >"${QA_SERVICE_LOG_DIR}/${name}-process.log" 2>&1 &
  local pid=$!
  QA_SERVICE_CLEANUPS+=("pid|${name}|${pid}")
  qa_service_wait_for_port "${port}" "Squid service ${name}"
  export HTTP_PROXY_PUBLIC="127.0.0.1:${port}"
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
    test-buckket-2.duckdb-minio.com \
    test-bucket-public.duckdb-minio.com; do
    if ! grep -Eq "(^|[[:space:]])$${host}([[:space:]]|$)" /etc/hosts; then
      echo "127.0.0.1 ${host}" | sudo tee -a /etc/hosts >/dev/null
    fi
  done
  (
    cd "${QA_SERVICE_UPSTREAM_ROOT}"
    ./scripts/generate_presigned_url.sh
  )
  pushd "${QA_SERVICE_UPSTREAM_ROOT}" >/dev/null
  # shellcheck disable=SC1091
  source ./scripts/run_s3_test_server.sh
  # shellcheck disable=SC1091
  source ./scripts/set_s3_test_server_variables.sh
  popd >/dev/null
  export TEST_PERSISTENT_SECRETS_AVAILABLE=true
  QA_SERVICE_CLEANUPS+=("httpfs-minio|${name}|${compose_file}")
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
  container="${container:0:63}"

  docker rm -f "${container}" >/dev/null 2>&1 || true
  docker run -d \
    --name "${container}" \
    -e "POSTGRES_USER=${username}" \
    -e "POSTGRES_PASSWORD=${password}" \
    -e "POSTGRES_DB=${database}" \
    -p "127.0.0.1:${port}:5432" \
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
  export MSSQL_TEST_DSN="Ù\™\IÓTÔÔSÕTÕÒÔÕK	ÓTÔÔSÕTÕÔÔ•NÑ]X˜\ÙOIÓTÔÔSÕTÕÑŸNÕ\Ù\ˆYIÓTÔÔSÕTÕÕTÑTŸNÔ\ÜÝÛÜ™IÓTÔÔSÕTÕÔTÔßH‚ˆ^ÜTÔÔSÕTÕÕT’OH›\ÜÜ[‹ËÉÓTÔÔSÕTÕÕTÑTŸN‰ÓTÔÔSÕTÕÔTÔßP	ÓTÔÔSÕTÕÒÔÕN‰ÓTÔÔSÕTÕÔÔ•KÉÓTÔÔSÕTÕÑŸH‚ˆ^ÜTÔÔSÕTÕ—ÑÓH”Ù\™\IÓTÔÔSÕTÕÒÔÕK	ÓTÔÔSÕTÕÔÔ•NÑ]X˜\ÙOU\ÝŽÕ\Ù\ˆYIÓTÔÔSÕTÕÕTÑTŸNÔ\ÜÝÛÜ™IÓTÔÔSÕTÕÔTÔßH‚ˆ^ÜTÔÔSÕTÕ—ÕT’OH›\ÜÜ[‹ËÉÓTÔÔSÕTÕÕTÑTŸN‰ÓTÔÔSÕTÕÔTÔßP	ÓTÔÔSÕTÕÒÔÕN‰ÓTÔÔSÕTÕÔÔ•KÕ\Ýˆ‚ˆ^ÜTÔÔSÕTÕÔÑT•‘TH‰ÓTÔÔSÕTÕÑÓŸH‚ˆ^ÜTÔÔSÕTÕÐÓÓ“‘PÕSÓ—ÔÕ’S‘ÏH‰ÓTÔSÕTÕÑÓŸH‚‚ˆØ]ˆ‰ÔPWÔÑT•’PÑWÕTÕ‘PSWÔ“ÓÕKË™[ˆˆSÑ‚“TÔÔSÕTÕÒÔÕIÓTÔÔSÕTÕÒÔÕB“TÔÔSÕTÕÔÔ•IÓTÔÔSÕTÕÔÔ•B“TÔÔSÕTÕÕTÑTIÓTÔÔSÕTÕÕTÑTŸB“TÔÔSÕTÕÔTÔÏIÓTÔÔSÕTÕÔTÔßB“TÔÔSÕTÕÑIÓTÔÔSÕTÕÑŸB‘SÑ‚‚ˆØÚÙ\ˆÛÛ\ÜÙHYˆ‰ØÛÛ\ÜÙWÙš[_Hˆ\‰Ü›Ú™XÝHˆ\YÜ[Ù\™\‚ˆØØ[ÛÛZ[™\‚ˆÛÛZ[™\H‰
ØÚÙ\ˆÛÛ\ÜÙHYˆ‰ØÛÛ\ÜÙWÙš[_Hˆ\‰Ü›Ú™XÝHˆÈ\HÜ[Ù\™\ŠH‚ˆYˆÖÈ^ˆ‰ØÛÛZ[™\ŸHˆWNÈ[‚ˆXÚÈ”ÔSÙ\™\ˆÙ\šXÙH	Û˜[Y_HY›ÝÜ™X]HHÛÛZ[™\ˆˆ‰Œ‚ˆ™]\›ˆBˆšBˆPWÔÑT•’PÑWÐÓPS•TÊÏJ˜ÛÛ\ÜÙ_	Û˜[Y__	ØÛÛ\ÜÙWÙš[__	Ü›Ú™XÝHŠBˆ›ÜˆÈ[ˆ	
Ù\HHŒ
NÈÂˆYˆØÚÙ\ˆ^XÈ‰ØÛÛZ[™\ŸHˆÛÜÛ\ÜÜ[]ÛÛÌNØš[‹ÜÜ[ÛYˆTÈØØ[ÜÝUH‰Ý\Ù\›˜[Y_HˆT‰Ü\ÜÝÛÜ™HˆPÈˆTH	ÔÑSPÕIÈ‹Ù]‹Û[‰ŒNÈ[‚ˆ^ÜÔSÑT•‘T—ÒQH‰ØÛÛZ[™\ŸH‚ˆ^ÜTÔÔSÐÓÓTÔÑWÑ’SOH‰ØÛÛ\ÜÙWÙš[_H‚ˆ^ÜTÔÔSÐÓÓTÔÑWÔ“Ò‘PÕH‰Ü›Ú™XÝH‚ˆ™]\›ˆˆšBˆÛY\‚ˆÛ™BˆXÚÈ”ÔSÙ\™\ˆÙ\šXÙH	Û˜[Y_HY›Ý™XÛÛYH™XYHˆ‰Œ‚ˆ™]\›ˆBŸB‚œXWÜÙ\šXÙWÜÝ\Ùš[J
HÂˆØØ[Ù\šXÙ\×Ùš[OIBˆYˆÖÈHYˆ‰ÜÙ\šXÙ\×Ùš[_HˆWNÈ[‚ˆXÚÈ”Ù\šXÙ\ÈX[šY™\Ý\ÈZ\ÜÚ[™Îˆ	ÜÙ\šXÙ\×Ùš[_Hˆ‰Œ‚ˆ™]\›ˆBˆšBˆÚ[HQ”ÏIß	È™XY\ˆ˜[YHÙ\šXÙWÝ\HÜ™\œÚ[Ûˆ]X˜\ÙH\Ù\›˜[YNÈÂˆÖÈ[ˆ‰Û˜[Y_HˆWHÛÛ[YBˆØ\ÙH‰ÜÙ\šXÙWÝ\_Hˆ[‚ˆ]Û‹Z
BˆXWÜÙ\šXÙWÜÝ\Ü]Û—Ú‰Û˜[Y_Hˆ‰ÜÜH‚ˆÎÂˆÜ]ZY
BˆXWÜÙ\šXÙWÜÝ\ÜÜ]ZY‰Û˜[Y_Hˆ‰ÜÜH‚ˆÎÂˆœË[Z[š[ÊBˆXWÜÙ\šXÙWÜÝ\Úœ×ÛZ[š[È‰Û˜[Y_H‚ˆÎÂˆÜÝÜ™\ÊBˆXWÜÙ\šXÙWÜÝ\ÜÜÝÜ™\Èˆ‰Û˜[Y_Hˆ‰ÜÜHˆ‰Ý™\œÚ[ÛŸHˆ‰Ù]X˜\Ù_Hˆ‰Ý\Ù\›˜[YN‹\ÜÝÜ™\ßH‚ˆÎÂˆÜ[Ù\™\ŠBˆXWÜÙ\šXÙWÜÝ\ÜÜ[Ù\™\ˆˆ‰Û˜[Y_Hˆ‰ÜÜHˆ‰Ý™\œÚ[ÛŸHˆ‰Ù]X˜\Ù_Hˆ‰Ý\Ù\›˜[YN‹\Ø_H‚ˆÎÂˆ
ŠBˆXÚÈ•[œÝ\ÜYÙ\šXÙH\Nˆ	ÜÙ\šXÙWÝ\_Hˆ‰Œ‚ˆ™]\›ˆ‚ˆÎÂˆ\ØXÂˆÛ™H
XWÜÙ\šXÙWÜ›ÝÜÈ‰ÜÙ\šXÙ\×Ùš[_HŠBŸB‚œXWÜ™\™\]Z\Ú]WØÚXÚ×Ùš[J
HÂˆØØ[™\™\]Z\Ú]\×Ùš[OIBˆ]ÛŒÈH‰Ü™\™\]Z\Ú]\×Ùš[_Hˆ	ÔIÈÚ[HQ”ÏH™XY\ˆ™\™\]Z\Ú]NÈÂš[\ÜœÛÛ‚š[\ÜÞ\Â™œ›ÛH]Xˆ[\Ü]š][\ÈHœÛÛ‹›ØYÊ]
Þ\Ë˜\™Ý–ÌWJKœ™XYÝ^
[˜ÛÙ[™ÏH]‹NŠJBšYˆ›Ý\Ú[œÝ[˜ÙJ][\Ë\Ý
N‚ˆ˜Z\ÙHÞ\Ý[Q^]
œ™\™\]Z\Ú]\ÈX[šY™\Ý]\ÝÛÛZ[ˆH\ÝŠB™›Üˆ][H[ˆ][\Î‚ˆš[
][VÈ\H—JB”BˆØ\ÙH‰Ü™\™\]Z\Ú]_Hˆ[‚ˆÛÛÙÛKXšYÜ]Y\žJBˆ›Üˆ˜\šXX›WÛ˜[YH[ˆÓÓÑÓWÐTPÐUSÓ—ÐÔ‘QS•PSÈ”WÕTÕÔ“Ò‘PÕ”WÕTÕÑUTÑUÈÂˆYˆÖÈ^ˆ‰È]˜\šXX›WÛ˜[YN‹_HˆWNÈ[‚ˆXÚÈ‘ÛÛÙÛHšYÔ]Y\žH™\™\]Z\Ú]H™\]Z\™\È	Ý˜\šXX›WÛ˜[Y_Hˆ‰Œ‚ˆ™]\›ˆBˆšBˆÛ™BˆÎÂˆ
ŠBˆXÚÈ•[œÝ\ÜY™\™\]Z\Ú]Nˆ	Ü™\™\]Z\Ú]_Hˆ‰Œ‚ˆ™]\›ˆ‚ˆÎÂˆ\ØXÂˆÛ™BŸB‚œXWÜÙ\šXÙWÜÝÜØ[

HÂˆØØ[[™^XÝ[ÛˆÚ[™˜[YH˜[YH^˜Bˆ›Üˆ

[™^IÈÔPWÔÑT•’PÑWÐÓPS•TÖÐ_KLNÈ[™^LÈ[™^KJJNÈÂˆXÝ[ÛH‰ÔPWÔÑT•’PÑWÐÓPS•TÖÚ[™^_H‚ˆQ”ÏIß	È™XY\ˆÚ[™˜[YH˜[YH^˜H‰ØXÝ[ÛŸH‚ˆØ\ÙH‰ÚÚ[™Hˆ[‚ˆY
BˆYˆÖÈ[ˆ‰Ý˜[Y_HˆWH	‰ˆÚ[L‰Ý˜[Y_Hˆ‹Ù]‹Û[È[‚ˆÚ[‰Ý˜[Y_HˆYBˆØZ]‰Ý˜[Y_Hˆ‹Ù]‹Û[YBˆšBˆÎÂˆœË[Z[š[ÊBˆ
ˆÙ‰ÔPWÔÑT•’PÑWÕTÕ‘PSWÔ“ÓÕH‚ˆØÚÙ\ˆÛÛ\ÜÙHYˆ‰Ý˜[Y_Hˆ\XÚÙ‹[Z[š[ÈÙÜÈK[›ËXÛÛÜ‚ˆ
Hˆ‰ÔPWÔÑT•’PÑWÓÑ×ÑTŸKÉÛ˜[Y_K›ÙÈˆ‰ŒHYBˆ
ˆÙ‰ÔPWÔÑT•’PÑWÕTÕ‘PSWÔ“ÓÕH‚ˆØÚÙ\ˆÛÛ\ÜÙHYˆ‰Ý˜[Y_Hˆ\XÚÙ‹[Z[š[ÈÝÛˆK]›Û[Y\ÈK\™[[Ý™K[Üœ[œÂˆ
Hˆ‰ÔPWÔÑT•’PÑWÓÑ×ÑTŸKÉÛ˜[Y_K›ÙÈˆ‰ŒHYBˆÎÂˆÛÛZ[™\ŠBˆØÚÙ\ˆÙÜÈ‰Ý˜[Y_Hˆˆ‰ÔPWÔÑT•’PÑWÓÑ×ÑTŸKÉÛ˜[Y_K›ÙÈˆ‰ŒHYBˆØÚÙ\ˆ›HYˆ‰Ý˜[Y_Hˆ‹Ù]‹Û[‰ŒHYBˆÎÂˆÛÛ\ÜÙJBˆØÚÙ\ˆÛÛ\ÜÙHYˆ‰Ý˜[Y_Hˆ\‰Ù^˜_HˆÙÜÈK[›ËXÛÛÜˆˆˆ‰ÔPWÔÑT•’PÑWÓÑ×ÑTŸKÉÛ˜[Y_K›ÙÈˆ‰ŒHYBˆØÚÙ\ˆÛÛ\ÜÙHYˆ‰Ý˜[Y_Hˆ\‰Ù^˜_HˆÝÛˆK]›Û[Y\ÈK\™[[Ý™K[Üœ[œÈˆˆ‰ÔPWÔÑT•’PÑWÓÑ×ÑTŸKÉÛ˜[Y_K›ÙÈˆ‰ŒHYBˆÎÂˆ\ØXÂˆÛ™BˆPWÔÑT•’PÑWÐÓPS•TÏJ
BŸB