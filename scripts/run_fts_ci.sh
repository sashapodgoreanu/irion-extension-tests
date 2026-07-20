#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${ROOT:-/duckdb_build_dir}"
DUCKDB_SRC="${ROOT}/upstream/duckdb"
FTS_SRC="${ROOT}/upstream/fts"
BUILD_DIR="${ROOT}/build/release"
REPORT_DIR="${ROOT}/build/reports"
TEST_HOME="${ROOT}/build/test-home"
LOCAL_EXTENSION_REPO="${BUILD_DIR}/repository"
EXTENSION_CONFIG="${ROOT}/cmake/fts_all_loaded.cmake"
TEST_CONFIG="${ROOT}/configs/fts_all_loaded.json"
BUILD_JOBS="${BUILD_JOBS:-2}"

mkdir -p "${BUILD_DIR}" "${REPORT_DIR}" "${TEST_HOME}"

for required_path in \
  "${DUCKDB_SRC}/CMakeLists.txt" \
  "${FTS_SRC}/extension_config.cmake" \
  "${FTS_SRC}/test/sql/fts" \
  "${EXTENSION_CONFIG}" \
  "${TEST_CONFIG}"; do
  if [[ ! -e "${required_path}" ]]; then
    echo "Missing required path: ${required_path}" >&2
    exit 2
  fi
done

{
  echo "duckdb_ref=${DUCKDB_REF:-unknown}"
  echo "ci_tools_ref=${CI_TOOLS_REF:-unknown}"
  echo "fts_ref=${FTS_REF:-unknown}"
  echo "duckdb_sha=$(git -C "${DUCKDB_SRC}" rev-parse HEAD)"
  echo "fts_sha=$(git -C "${FTS_SRC}" rev-parse HEAD)"
  echo "platform=${DUCKDB_PLATFORM:-linux_amd64}"
  echo "build_type=Release"
  echo "linkage=dynamic"
  echo "test_dir=${FTS_SRC}"
  echo "local_extension_repo=${LOCAL_EXTENSION_REPO}"
} | tee "${REPORT_DIR}/metadata.txt"

echo "::group::Configure DuckDB and loadable FTS"
cmake -G Ninja \
  -S "${DUCKDB_SRC}" \
  -B "${BUILD_DIR}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_TOOLCHAIN_FILE="${VCPKG_TOOLCHAIN_PATH:-/vcpkg/scripts/buildsystems/vcpkg.cmake}" \
  -DVCPKG_TARGET_TRIPLET="${VCPKG_TARGET_TRIPLET:-x64-linux-release}" \
  -DDUCKDB_EXPLICIT_PLATFORM="${DUCKDB_PLATFORM:-linux_amd64}" \
  -DDUCKDB_EXTENSION_CONFIGS="${EXTENSION_CONFIG}" \
  -DTEST_WITH_LOADABLE_EXTENSION=fts \
  -DENABLE_EXTENSION_AUTOLOADING=OFF \
  -DENABLE_EXTENSION_AUTOINSTALL=OFF \
  2>&1 | tee "${REPORT_DIR}/configure.log"
echo "::endgroup::"

echo "::group::Build DuckDB unittest and the local extension repository"
cmake --build "${BUILD_DIR}" \
  --target duckdb unittest fts_loadable_extension duckdb_local_extension_repo \
  --parallel "${BUILD_JOBS}" \
  2>&1 | tee "${REPORT_DIR}/build.log"
echo "::endgroup::"

DUCKDB_BIN="${BUILD_DIR}/duckdb"
UNITTEST_BIN="${BUILD_DIR}/test/unittest"
FTS_EXTENSION=$(find "${LOCAL_EXTENSION_REPO}" -type f -name 'fts.duckdb_extension' -print -quit)

if [[ ! -x "${DUCKDB_BIN}" ]]; then
  echo "DuckDB executable was not produced: ${DUCKDB_BIN}" >&2
  exit 3
fi
if [[ ! -x "${UNITTEST_BIN}" ]]; then
  echo "DuckDB unittest executable was not produced: ${UNITTEST_BIN}" >&2
  exit 3
fi
if [[ -z "${FTS_EXTENSION}" ]]; then
  echo "The local repository does not contain fts.duckdb_extension: ${LOCAL_EXTENSION_REPO}" >&2
  exit 3
fi

echo "fts_extension=${FTS_EXTENSION}" | tee -a "${REPORT_DIR}/metadata.txt"

echo "::group::Pre-flight: prove FTS is not statically loaded, then INSTALL/LOAD it"
HOME="${TEST_HOME}" "${DUCKDB_BIN}" -unsigned -c "
SELECT CASE
  WHEN count(*) = 0 THEN 'fts is not statically loaded'
  ELSE error('fts was already loaded before INSTALL/LOAD')
END AS before_dynamic_load
FROM duckdb_extensions()
WHERE extension_name = 'fts' AND loaded;

INSTALL fts FROM '${LOCAL_EXTENSION_REPO}';
LOAD fts;

SELECT CASE
  WHEN count(*) = 1 THEN 'fts dynamically installed and loaded'
  ELSE error('fts was not dynamically loaded')
END AS after_dynamic_load
FROM duckdb_extensions()
WHERE extension_name = 'fts' AND loaded;

SELECT extension_name, loaded, installed, extension_version, install_mode, installed_from
FROM duckdb_extensions()
WHERE extension_name = 'fts';
" 2>&1 | tee "${REPORT_DIR}/preflight.log"
echo "::endgroup::"

echo "::group::Inventory upstream FTS tests"
find "${FTS_SRC}/test/sql/fts" -type f \
  \( -name '*.test' -o -name '*.test_slow' \) \
  -printf '%P\n' \
  | sort \
  | tee "${REPORT_DIR}/upstream-tests.txt"

UPSTREAM_TESTS=$(wc -l < "${REPORT_DIR}/upstream-tests.txt")
if [[ "${UPSTREAM_TESTS}" -eq 0 ]]; then
  echo "No SQLLogicTests found in ${FTS_SRC}/test/sql/fts." >&2
  exit 4
fi
printf 'upstream_fts_tests=%s\n' "${UPSTREAM_TESTS}" | tee -a "${REPORT_DIR}/metadata.txt"
echo "::endgroup::"

echo "::group::Run the FTS repository test directory through DuckDB unittest"
printf '%q ' "${UNITTEST_BIN}" --test-config "${TEST_CONFIG}" --test-dir "${FTS_SRC}" 'test/sql/fts/*'
printf '\n'

HOME="${TEST_HOME}" "${UNITTEST_BIN}" \
  --test-config "${TEST_CONFIG}" \
  --test-dir "${FTS_SRC}" \
  "test/sql/fts/*" \
  2>&1 | tee "${REPORT_DIR}/test-output.log"
echo "::endgroup::"

echo "Dynamic FTS compatibility test completed successfully."
