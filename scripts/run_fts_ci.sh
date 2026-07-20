#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${ROOT:-/duckdb_build_dir}"
DUCKDB_SRC="${ROOT}/upstream/duckdb"
FTS_SRC="${ROOT}/upstream/fts"
BUILD_DIR="${ROOT}/build/release"
REPORT_DIR="${ROOT}/build/reports"
EXTENSION_CONFIG="${ROOT}/cmake/fts_all_loaded.cmake"
TEST_CONFIG="${ROOT}/configs/fts_all_loaded.json"
BUILD_JOBS="${BUILD_JOBS:-2}"

mkdir -p "${BUILD_DIR}" "${REPORT_DIR}"

for required_path in \
  "${DUCKDB_SRC}/CMakeLists.txt" \
  "${FTS_SRC}/extension_config.cmake" \
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
} | tee "${REPORT_DIR}/metadata.txt"

echo "::group::Configure DuckDB, ICU and FTS"
cmake -G Ninja \
  -S "${DUCKDB_SRC}" \
  -B "${BUILD_DIR}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_TOOLCHAIN_FILE="${VCPKG_TOOLCHAIN_PATH:-/vcpkg/scripts/buildsystems/vcpkg.cmake}" \
  -DVCPKG_TARGET_TRIPLET="${VCPKG_TARGET_TRIPLET:-x64-linux-release}" \
  -DDUCKDB_EXPLICIT_PLATFORM="${DUCKDB_PLATFORM:-linux_amd64}" \
  -DDUCKDB_EXTENSION_CONFIGS="${EXTENSION_CONFIG}" \
  -DUNITTEST_ROOT_DIRECTORY="${FTS_SRC}" \
  -DBENCHMARK_ROOT_DIRECTORY="${FTS_SRC}" \
  -DENABLE_EXTENSION_AUTOLOADING=OFF \
  -DENABLE_EXTENSION_AUTOINSTALL=OFF \
  2>&1 | tee "${REPORT_DIR}/configure.log"
echo "::endgroup::"

echo "::group::Build the single DuckDB test runner"
cmake --build "${BUILD_DIR}" \
  --target duckdb unittest \
  --parallel "${BUILD_JOBS}" \
  2>&1 | tee "${REPORT_DIR}/build.log"
echo "::endgroup::"

DUCKDB_BIN="${BUILD_DIR}/duckdb"
UNITTEST_BIN="${BUILD_DIR}/test/unittest"

if [[ ! -x "${DUCKDB_BIN}" ]]; then
  echo "DuckDB executable was not produced: ${DUCKDB_BIN}" >&2
  exit 3
fi
if [[ ! -x "${UNITTEST_BIN}" ]]; then
  echo "DuckDB unittest executable was not produced: ${UNITTEST_BIN}" >&2
  exit 3
fi

echo "::group::Pre-flight: prove ICU and FTS are loaded together"
"${DUCKDB_BIN}" -c "
LOAD icu;
LOAD fts;
SELECT CASE
  WHEN count(*) = 2 THEN 'all configured extensions loaded'
  ELSE error('ICU or FTS is not loaded')
END AS compatibility_preflight
FROM duckdb_extensions()
WHERE extension_name IN ('icu', 'fts') AND loaded;
SELECT extension_name, loaded, installed, extension_version
FROM duckdb_extensions()
WHERE extension_name IN ('icu', 'fts')
ORDER BY extension_name;
" 2>&1 | tee "${REPORT_DIR}/preflight.log"
echo "::endgroup::"

echo "::group::Verify that upstream FTS tests are registered"
"${UNITTEST_BIN}" \
  --test-config "${TEST_CONFIG}" \
  --list-tests \
  "test/sql/fts/*" \
  2>&1 | tee "${REPORT_DIR}/registered-tests.txt"

echo "::endgroup::"

REGISTERED_TESTS=$(grep -c "test/sql/fts/" "${REPORT_DIR}/registered-tests.txt" || true)
if [[ "${REGISTERED_TESTS}" -eq 0 ]]; then
  echo "No upstream duckdb-fts SQLLogicTests were registered in unittest." >&2
  exit 4
fi
printf 'registered_fts_tests=%s\n' "${REGISTERED_TESTS}" | tee -a "${REPORT_DIR}/metadata.txt"

echo "::group::Run all upstream FTS tests with ICU and FTS preloaded"
cd "${FTS_SRC}"
"${UNITTEST_BIN}" \
  --test-config "${TEST_CONFIG}" \
  "test/sql/fts/*" \
  2>&1 | tee "${REPORT_DIR}/test-output.log"
echo "::endgroup::"

echo "FTS all-loaded compatibility test completed successfully."
