#!/usr/bin/env bash
set -Eeuo pipefail

DUCKDB_VERSION="${DUCKDB_VERSION:-v1.5.4}"
CI_TOOLS_VERSION="${CI_TOOLS_VERSION:?pinned extension-ci-tools SHA is required}"
BUILD_JOBS="${BUILD_JOBS:-2}"

# The repository pins both sources as Git submodules. actions/checkout
# already checks them out; refetching a version tag discards that reproducible
# pin. In particular, extension-ci-tools does not have a v2.0.0 release tag.
DUCKDB_TAG_COMMIT="$(git -C duckdb rev-parse --verify "refs/tags/${DUCKDB_VERSION}^{commit}")"
DUCKDB_COMMIT="$(git -C duckdb rev-parse HEAD)"
CI_TOOLS_COMMIT="$(git -C extension-ci-tools rev-parse HEAD)"
if [[ "${DUCKDB_COMMIT}" != "${DUCKDB_TAG_COMMIT}" ]]; then
  echo "DuckDB submodule does not match release ${DUCKDB_VERSION}: ${DUCKDB_COMMIT} != ${DUCKDB_TAG_COMMIT}" >&2
  exit 1
fi
if [[ "${CI_TOOLS_COMMIT}" != "${CI_TOOLS_VERSION}" ]]; then
  echo "extension-ci-tools submodule does not match configured SHA: ${CI_TOOLS_COMMIT} != ${CI_TOOLS_VERSION}" >&2
  exit 1
fi
echo "Using pinned DuckDB ${DUCKDB_COMMIT} and extension-ci-tools ${CI_TOOLS_COMMIT}"

# The upstream HTTPFS fixture script invokes DBGEN in a fresh DuckDB CLI process.
# Keep normal CLI autoload/autoinstall available; unittest still uses our explicit
# test configuration with autoloading disabled.
GEN=ninja \
make release -j"${BUILD_JOBS}"
cmake --build build/release --target unittest --parallel "${BUILD_JOBS}"

rm -rf build/artifact
mkdir -p build/artifact/bin build/artifact/lib build/artifact/extensions build/artifact/logs

install -m 0755 build/release/duckdb build/artifact/bin/duckdb
install -m 0755 build/release/test/unittest build/artifact/bin/unittest

# DuckDB 2.0 Linux unittest links libduckdb.so; bundle the shared library.
if [[ ! -f build/release/src/libduckdb.so ]]; then
  echo "Missing DuckDB 2.0 shared library: build/release/src/libduckdb.so" >&2
  exit 1
fi
cp -a build/release/src/libduckdb.so* build/artifact/lib/
export LD_LIBRARY_PATH="$(pwd)/build/artifact/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

find build/release/extension/qa_test -type f -name '*.duckdb_extension' \
  -exec install -m 0644 {} build/artifact/extensions/ \;

if ! find build/artifact/extensions -type f -name 'qa_test*.duckdb_extension' -print -quit | grep -q .; then
  echo "qa_test extension output was not produced" >&2
  exit 1
fi

{
  echo "duckdb_version=${DUCKDB_VERSION}"
  echo "duckdb_commit=$(git -C duckdb rev-parse HEAD)"
  echo "ci_tools_version=${CI_TOOLS_VERSION}"
  echo "ci_tools_commit=$(git -C extension-ci-tools rev-parse HEAD)"
  echo "shared_library=libduckdb.so"
  echo "compiled_extension=qa_test"
  echo "cli_extension_autoloading=enabled"
  echo "cli_extension_autoinstall=enabled"
} | tee build/artifact/logs/build-info.txt

build/artifact/bin/duckdb --version
ldd build/artifact/bin/unittest | tee build/artifact/logs/unittest-ldd.txt
if grep -q 'not found' build/artifact/logs/unittest-ldd.txt; then
  echo "Unresolved shared dependencies in Linux unittest" >&2
  exit 1
fi
build/artifact/bin/unittest --help >/dev/null
