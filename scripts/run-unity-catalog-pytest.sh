#!/usr/bin/env bash
set -Eeuo pipefail

UPSTREAM_ROOT="${1:?upstream Unity Catalog checkout is required}"
RUNTIME_CONFIG_DIR="${2:?resolved battery runtime config is required}"
DUCKDB_VERSION="${3:?DuckDB version is required}"
EXPECTED_UPSTREAM_REF="${4:?pinned Unity Catalog source commit is required}"
UPSTREAM_ROOT="$(cd "${UPSTREAM_ROOT}" && pwd)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ARTIFACT_DIR="${ARTIFACT_DIR:-${REPOSITORY_ROOT}/build/artifact}"
ARTIFACT_DIR="$(cd "${ARTIFACT_DIR}" && pwd)"
BUILD_DIR="${UPSTREAM_ROOT}/build/release"
LOG_DIR="${REPOSITORY_ROOT}/build/logs/unity_catalog"
DUCKDB_BIN="${ARTIFACT_DIR}/bin/duckdb"

required=(
  "${UPSTREAM_ROOT}/pyproject.toml" \
  "${UPSTREAM_ROOT}/pytest.ini" \
  "${UPSTREAM_ROOT}/test/conftest.py" \
  "${ARTIFACT_DIR}/bin/duckdb" \
  "${ARTIFACT_DIR}/bin/unittest" \
  "${RUNTIME_CONFIG_DIR}/install-extensions.sql" \
  "${RUNTIME_CONFIG_DIR}/init-extensions.sql" \
  "${RUNTIME_CONFIG_DIR}/extensions.json"
)
# The Windows WSL bridge supplies proxies to native duckdb.exe/unittest.exe.
# It does not have a Linux shared library, and those native binaries do not use
# libduckdb.so. Linux runs use the built shared library for Python/C++ tests.
if [[ "${QA_NATIVE_WINDOWS:-0}" != "1" ]]; then
  required+=("${ARTIFACT_DIR}/lib/libduckdb.so")
fi

for required_file in "${required[@]}"; do
  if [[ ! -e "${required_file}" ]]; then
    echo "Unity Catalog pytest prerequisite is missing: ${required_file}" >&2
    exit 1
  fi
done

actual_upstream_ref="$(git -C "${UPSTREAM_ROOT}" rev-parse HEAD)"
if [[ "${actual_upstream_ref}" != "${EXPECTED_UPSTREAM_REF}" ]]; then
  echo "Unity Catalog checkout must be ${EXPECTED_UPSTREAM_REF}; found ${actual_upstream_ref}" >&2
  exit 1
fi

mkdir -p "${BUILD_DIR}/test" "${BUILD_DIR}/src" "${LOG_DIR}"
ln -sfn "${ARTIFACT_DIR}/bin/unittest" "${BUILD_DIR}/test/unittest"
if [[ -x "${ARTIFACT_DIR}/bin/unittest_cpp" ]]; then
  ln -sfn "${ARTIFACT_DIR}/bin/unittest_cpp" "${BUILD_DIR}/test/unittest_cpp"
fi
ln -sfn "${ARTIFACT_DIR}/bin/duckdb" "${BUILD_DIR}/duckdb"
if [[ -f "${ARTIFACT_DIR}/lib/libduckdb.so" ]]; then
  ln -sfn "${ARTIFACT_DIR}/lib/libduckdb.so" "${BUILD_DIR}/src/libduckdb.so"
fi

export BUILD_DIR
export DUCKTEST_UC_IMAGE="${DUCKTEST_UC_IMAGE:-ghcr.io/benfleis/ducktest-unitycatalog:ci}"
export LD_LIBRARY_PATH="${BUILD_DIR}/src"

SQL_FILE="${LOG_DIR}/install-extensions.sql"
EXTENSION_CSV="${LOG_DIR}/extensions.csv"
cat \
  "${RUNTIME_CONFIG_DIR}/install-extensions.sql" \
  "${RUNTIME_CONFIG_DIR}/init-extensions.sql" >"${SQL_FILE}"
cat >>"${SQL_FILE}" <<'SQL'
SELECT extension_name, installed, loaded, extension_version, install_mode, installed_from
FROM duckdb_extensions()
ORDER BY extension_name;
SQL

"${DUCKDB_BIN}" -csv -header <"${SQL_FILE}" >"${EXTENSION_CSV}"
python3 "${SCRIPT_DIR}/validate-extension-probe.py" \
  "${EXTENSION_CSV}" \
  "${RUNTIME_CONFIG_DIR}/extensions.json"

version_root="${HOME}/.duckdb/extensions/${DUCKDB_VERSION}"
if [[ ! -d "${version_root}" ]]; then
  echo "DuckDB extension version directory was not created: ${version_root}" >&2
  exit 1
fi
extension_dir="$(find "${version_root}" -mindepth 2 -maxdepth 2 -type f \
  -name '*.duckdb_extension' -printf '%h\n' -quit)"
if [[ -z "${extension_dir}" ]]; then
  echo "No installed extension binaries found under ${version_root}" >&2
  exit 1
fi
platform="$(basename "${extension_dir}")"
repository_platform="${BUILD_DIR}/repository/${DUCKDB_VERSION}/${platform}"
mkdir -p "${repository_platform}"
cp -a "${extension_dir}/." "${repository_platform}/"
if ! compgen -G "${repository_platform}/*.duckdb_extension" >/dev/null; then
  echo "No installed extensions were staged under ${repository_platform}" >&2
  exit 1
fi
while IFS= read -r -d '' extension_binary; do
  extension_name="${extension_binary##*/}"
  extension_name="${extension_name%.duckdb_extension}"
  extension_build_dir="${BUILD_DIR}/extension/${extension_name}"
  mkdir -p "${extension_build_dir}"
  cp -a "${extension_binary}" "${extension_build_dir}/${extension_name}.duckdb_extension"
done < <(find "${extension_dir}" -maxdepth 1 -type f -name '*.duckdb_extension' -print0)
export LOCAL_EXTENSION_REPO="${BUILD_DIR}/repository"

echo "Unity Catalog suite image: ${DUCKTEST_UC_IMAGE}" | tee "${LOG_DIR}/pytest.log"
docker pull "${DUCKTEST_UC_IMAGE}" 2>&1 | tee -a "${LOG_DIR}/pytest.log"
(
  cd "${UPSTREAM_ROOT}"
  # Match the pinned upstream Integration Tests workflow. Its pytest driver
  # selects all default local suites and deselects Databricks unless requested.
  PYTHONPATH="${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
    BUILD_DIR=build/release \
    LD_LIBRARY_PATH="${PWD}/build/release/src" \
    uv run pytest -p unity_catalog_http_error_plugin -n0 -s
) 2>&1 | tee -a "${LOG_DIR}/pytest.log"
