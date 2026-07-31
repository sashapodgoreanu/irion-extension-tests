#!/usr/bin/env bash
set -Eeuo pipefail

UPSTREAM_ROOT="${1:?upstream root is required}"
RUNTIME_ROOT="${2:?runtime root is required}"
LOG_DIR="${3:?log directory is required}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_PATH="${REPOSITORY_ROOT}/config/extensions.yml"
ENV_FILE="${RUNTIME_ROOT}/delta-local.env"
KERNEL_ROOT="${UPSTREAM_ROOT}/build/release/rust/src/delta_kernel"
VENV_ROOT="${RUNTIME_ROOT}/delta-python"
MINIO_COMPOSE="${RUNTIME_ROOT}/httpfs-minio.yml"
MINIO_CONTAINER="qa-delta-minio-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
MINIO_CONTAINER="${MINIO_CONTAINER:0:63}"

mkdir -p "${RUNTIME_ROOT}" "${LOG_DIR}"

for command_name in git cargo java make python3 docker curl awk sed grep; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Delta local test preparation requires ${command_name}" >&2
    exit 1
  }
done

for required in \
  "${UPSTREAM_ROOT}/CMakeLists.txt" \
  "${UPSTREAM_ROOT}/Makefile" \
  "${UPSTREAM_ROOT}/scripts/create_minio_credential_file.sh" \
  "${UPSTREAM_ROOT}/scripts/env_minio" \
  "${UPSTREAM_ROOT}/scripts/upload_test_files_to_minio.sh" \
  "${UPSTREAM_ROOT}/scripts/unwrap_golden_tables.sh" \
  "${CONFIG_PATH}"; do
  if [[ ! -f "${required}" ]]; then
    echo "Delta upstream contract input is missing: ${required}" >&2
    exit 1
  fi
done

for target in generate-data unpack-golden-tables-release; do
  grep -Eq "^${target}:" "${UPSTREAM_ROOT}/Makefile" || {
    echo "Delta upstream Makefile no longer exposes ${target}" >&2
    exit 1
  }
done
for variable_name in DELTA_KERNEL_TESTS_PATH DAT_PATH; do
  grep -q "${variable_name}" "${UPSTREAM_ROOT}/Makefile" || {
    echo "Delta upstream Makefile no longer defines ${variable_name}" >&2
    exit 1
  }
done

KERNEL_REPOSITORY="$(
  sed -n 's/^[[:space:]]*GIT_REPOSITORY[[:space:]]*"\([^"]*\)".*/\1/p' \
    "${UPSTREAM_ROOT}/CMakeLists.txt" | head -n 1
)"
KERNEL_TAG="$(
  sed -n 's/^[[:space:]]*GIT_TAG[[:space:]]*\([^[:space:])]*\).*/\1/p' \
    "${UPSTREAM_ROOT}/CMakeLists.txt" | head -n 1
)"
if [[ -z "${KERNEL_REPOSITORY}" || -z "${KERNEL_TAG}" ]]; then
  echo "Unable to resolve delta-kernel-rs repository and tag from CMakeLists.txt" >&2
  exit 1
fi

HTTPFS_PIN="$(
  awk '
    /^  httpfs:$/ { in_httpfs=1; next }
    in_httpfs && /^  [a-z0-9_]+:$/ { exit }
    in_httpfs && /^[[:space:]]+pin:/ { print $2; exit }
  ' "${CONFIG_PATH}"
)"
if [[ ! "${HTTPFS_PIN}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Unable to resolve the pinned HTTPFS commit from ${CONFIG_PATH}" >&2
  exit 1
fi

curl --fail --location --silent --show-error \
  "https://raw.githubusercontent.com/duckdb/duckdb-httpfs/${HTTPFS_PIN}/scripts/minio_s3.yml" \
  --output "${MINIO_COMPOSE}"

MINIO_IMAGE="$(
  awk '
    /^[[:space:]]+minio:$/ { in_minio=1; next }
    in_minio && /^[[:space:]]+image:/ { print $2; exit }
  ' "${MINIO_COMPOSE}"
)"
MC_IMAGE="$(
  awk '
    /^[[:space:]]+minio_setup:$/ { in_setup=1; next }
    in_setup && /^[[:space:]]+image:/ { print $2; exit }
  ' "${MINIO_COMPOSE}"
)"
MINIO_ROOT_USER="$(sed -n 's/^[[:space:]]*-[[:space:]]*MINIO_ROOT_USER=//p' "${MINIO_COMPOSE}" | head -n 1)"
MINIO_ROOT_PASSWORD="$(sed -n 's/^[[:space:]]*-[[:space:]]*MINIO_ROOT_PASSWORD=//p' "${MINIO_COMPOSE}" | head -n 1)"
for value_name in MINIO_IMAGE MC_IMAGE MINIO_ROOT_USER MINIO_ROOT_PASSWORD; do
  if [[ -z "${!value_name:-}" ]]; then
    echo "Unable to resolve ${value_name} from HTTPFS MinIO contract at ${HTTPFS_PIN}" >&2
    exit 1
  fi
done

mapfile -t DELTA_MINIO_ENV < <(
  bash "${UPSTREAM_ROOT}/scripts/env_minio" bash -c \
    'printf "%s\n" "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" "$AWS_DEFAULT_REGION" "$AWS_ENDPOINT"'
)
if [[ "${#DELTA_MINIO_ENV[@]}" -ne 4 ]]; then
  echo "Delta env_minio no longer exports the expected four-value contract" >&2
  exit 1
fi
AWS_ACCESS_KEY_ID="${DELTA_MINIO_ENV[0]}"
AWS_SECRET_ACCESS_KEY="${DELTA_MINIO_ENV[1]}"
AWS_DEFAULT_REGION="${DELTA_MINIO_ENV[2]}"
AWS_ENDPOINT="${DELTA_MINIO_ENV[3]}"
if [[ "${AWS_ENDPOINT}" != "http://duckdb-minio.com:9000" ]]; then
  echo "Unsupported Delta MinIO endpoint contract: ${AWS_ENDPOINT}" >&2
  exit 1
fi

rm -rf "${KERNEL_ROOT}" "${VENV_ROOT}" "${UPSTREAM_ROOT}/data/generated" \
  "${UPSTREAM_ROOT}/data/unpacked_golden_tables"
mkdir -p "$(dirname "${KERNEL_ROOT}")"
git clone --quiet --depth 1 --branch "${KERNEL_TAG}" \
  "${KERNEL_REPOSITORY}" "${KERNEL_ROOT}"
KERNEL_COMMIT="$(git -C "${KERNEL_ROOT}" rev-parse HEAD)"

# Match the upstream CMake build: avoid unrelated benchmark downloads, then
# build the acceptance package so its build script downloads and extracts DAT.
mkdir -p "${KERNEL_ROOT}/benchmarks/workloads"
touch "${KERNEL_ROOT}/benchmarks/workloads/.done"
cargo build --manifest-path "${KERNEL_ROOT}/acceptance/Cargo.toml" \
  2>&1 | tee "${LOG_DIR}/delta-kernel-acceptance-build.log"

python3 -m venv "${VENV_ROOT}"
# shellcheck disable=SC1091
source "${VENV_ROOT}/bin/activate"
JAVA_HOME="$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")"
export JAVA_HOME
make -C "${UPSTREAM_ROOT}" generate-data unpack-golden-tables-release \
  2>&1 | tee "${LOG_DIR}/delta-generated-data.log"

if ! command -v aws >/dev/null 2>&1; then
  python3 -m pip install --disable-pip-version-check awscli \
    2>&1 | tee "${LOG_DIR}/delta-aws-cli-install.log"
fi

DELTA_KERNEL_TESTS_PATH="${KERNEL_ROOT}/kernel/tests/data"
DAT_PATH="${KERNEL_ROOT}/acceptance/tests/dat"
GOLDEN_TABLES_PATH="${UPSTREAM_ROOT}/data/unpacked_golden_tables"
for required_directory in \
  "${DELTA_KERNEL_TESTS_PATH}" \
  "${DAT_PATH}/out/reader_tests/generated" \
  "${GOLDEN_TABLES_PATH}" \
  "${UPSTREAM_ROOT}/data/generated"; do
  if [[ ! -d "${required_directory}" ]]; then
    echo "Prepared Delta fixture directory is missing: ${required_directory}" >&2
    exit 1
  fi
done

for host_name in \
  duckdb-minio.com \
  test-bucket.duckdb-minio.com \
  test-bucket-public.duckdb-minio.com; do
  if ! grep -Eq "(^|[[:space:]])${host_name}([[:space:]]|$)" /etc/hosts; then
    echo "127.0.0.1 ${host_name}" | sudo tee -a /etc/hosts >/dev/null
  fi
done

docker rm -f "${MINIO_CONTAINER}" >/dev/null 2>&1 || true
cleanup_failed_minio() {
  docker logs "${MINIO_CONTAINER}" >"${LOG_DIR}/delta-minio.log" 2>&1 || true
  docker rm -f "${MINIO_CONTAINER}" >/dev/null 2>&1 || true
}
trap cleanup_failed_minio ERR

docker run --detach \
  --name "${MINIO_CONTAINER}" \
  --publish 127.0.0.1:9000:9000 \
  --env "MINIO_ROOT_USER=${MINIO_ROOT_USER}" \
  --env "MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}" \
  --env "MINIO_REGION_NAME=${AWS_DEFAULT_REGION}" \
  --env "MINIO_DOMAIN=duckdb-minio.com" \
  "${MINIO_IMAGE}" server /data \
  >"${LOG_DIR}/delta-minio-container-id.txt"

for _ in $(seq 1 90); do
  if python3 - <<'PY'
import socket
try:
    with socket.create_connection(("127.0.0.1", 9000), timeout=1):
        pass
except OSError:
    raise SystemExit(1)
PY
  then
    break
  fi
  sleep 1
done
python3 - <<'PY'
import socket
with socket.create_connection(("127.0.0.1", 9000), timeout=2):
    pass
PY

docker run --rm --network host --entrypoint /bin/sh "${MC_IMAGE}" -c "
  set -eu
  until /usr/bin/mc alias set qa http://127.0.0.1:9000 '${MINIO_ROOT_USER}' '${MINIO_ROOT_PASSWORD}'; do sleep 1; done
  /usr/bin/mc admin user add qa '${AWS_ACCESS_KEY_ID}' '${AWS_SECRET_ACCESS_KEY}'
  /usr/bin/mc admin policy attach qa readwrite --user '${AWS_ACCESS_KEY_ID}'
  /usr/bin/mc mb --ignore-existing qa/test-bucket
  /usr/bin/mc version enable qa/test-bucket
  /usr/bin/mc mb --ignore-existing qa/test-bucket-public
  /usr/bin/mc anonymous set public qa/test-bucket-public
" 2>&1 | tee "${LOG_DIR}/delta-minio-setup.log"

(
  cd "${UPSTREAM_ROOT}"
  bash ./scripts/create_minio_credential_file.sh
  bash ./scripts/env_minio ./scripts/upload_test_files_to_minio.sh
) 2>&1 | tee "${LOG_DIR}/delta-minio-upload.log"

cat >"${ENV_FILE}" <<EOF
export GENERATED_DATA_AVAILABLE=1
export GOLDEN_TABLES_PATH=$(printf '%q' "${GOLDEN_TABLES_PATH}")
export DELTA_KERNEL_TESTS_PATH=$(printf '%q' "${DELTA_KERNEL_TESTS_PATH}")
export DAT_PATH=$(printf '%q' "${DAT_PATH}")
export S3_TEST_SERVER_AVAILABLE=1
export DUCKDB_MINIO_TEST_SERVER_AVAILABLE=1
export AWS_ACCESS_KEY_ID=$(printf '%q' "${AWS_ACCESS_KEY_ID}")
export AWS_SECRET_ACCESS_KEY=$(printf '%q' "${AWS_SECRET_ACCESS_KEY}")
export AWS_DEFAULT_REGION=$(printf '%q' "${AWS_DEFAULT_REGION}")
export AWS_ENDPOINT=$(printf '%q' "${AWS_ENDPOINT}")
export DELTA_MINIO_CONTAINER=$(printf '%q' "${MINIO_CONTAINER}")
EOF

{
  echo "delta_kernel_repository=${KERNEL_REPOSITORY}"
  echo "delta_kernel_tag=${KERNEL_TAG}"
  echo "delta_kernel_commit=${KERNEL_COMMIT}"
  echo "httpfs_pin=${HTTPFS_PIN}"
  echo "minio_image=${MINIO_IMAGE}"
  echo "mc_image=${MC_IMAGE}"
} >"${LOG_DIR}/delta-local-contract.txt"

trap - ERR
echo "Prepared Delta local fixtures and MinIO environment: ${ENV_FILE}"
