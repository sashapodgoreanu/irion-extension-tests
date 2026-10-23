#!/usr/bin/env bash
set -Eeuo pipefail

# Generate the upstream Delta Lake fixtures needed for local SQLLogicTests.
# MinIO/S3 is intentionally excluded; see the two scoped ignoredTests entries
# under testBatteries.delta in config/extensions.yml.
UPSTREAM_ROOT="${1:?upstream root is required}"
RUNTIME_ROOT="${2:?runtime root is required}"
LOG_DIR="${3:?log directory is required}"
ENV_FILE="${RUNTIME_ROOT}/delta-local.env"
KERNEL_ROOT="${UPSTREAM_ROOT}/build/release/rust/src/delta_kernel"
VENV_ROOT="${RUNTIME_ROOT}/delta-python"

mkdir -p "${RUNTIME_ROOT}" "${LOG_DIR}"

for command_name in git cargo java make python3 sed grep; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Delta local fixture preparation requires ${command_name}" >&2
    exit 1
  }
done

for required in \
  "${UPSTREAM_ROOT}/CMakeLists.txt" \
  "${UPSTREAM_ROOT}/Makefile" \
  "${UPSTREAM_ROOT}/scripts/unwrap_golden_tables.sh"; do
  if [[ ! -f "${required}" ]]; then
    echo "Delta upstream local fixture input is missing: ${required}" >&2
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

# Intentionally do not export S3 or MinIO availability flags: associated
# upstream tests require an object-storage service we no longer start.
cat >"${ENV_FILE}" <<EOF
unset S3_TEST_SERVER_AVAILABLE DUCKDB_MINIO_TEST_SERVER_AVAILABLE
export GENERATED_DATA_AVAILABLE=1
export GOLDEN_TABLES_PATH=$(printf '%q' "${GOLDEN_TABLES_PATH}")
export DELTA_KERNEL_TESTS_PATH=$(printf '%q' "${DELTA_KERNEL_TESTS_PATH}")
export DAT_PATH=$(printf '%q' "${DAT_PATH}")
EOF

{
  echo "delta_kernel_repository=${KERNEL_REPOSITORY}"
  echo "delta_kernel_tag=${KERNEL_TAG}"
  echo "delta_kernel_commit=${KERNEL_COMMIT}"
  echo "fixture_mode=local-only"
} >"${LOG_DIR}/delta-local-contract.txt"

echo "Prepared Delta local filesystem fixtures (without MinIO): ${ENV_FILE}"
