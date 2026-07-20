#!/usr/bin/env bash
set -Eeuo pipefail

DUCKDB_VERSION="${DUCKDB_VERSION:-v1.5.4}"
CI_TOOLS_VERSION="${CI_TOOLS_VERSION:-v1.5.4}"
BUILD_JOBS="${BUILD_JOBS:-2}"

checkout_ref() {
  local directory=$1
  local ref=$2
  git -C "${directory}" fetch --depth 1 origin "${ref}"
  git -C "${directory}" checkout --detach FETCH_HEAD
}

checkout_ref duckdb "${DUCKDB_VERSION}"
checkout_ref extension-ci-tools "${CI_TOOLS_VERSION}"

GEN=ninja make release -j"${BUILD_JOBS}"
cmake --build build/release --target unittest --parallel "${BUILD_JOBS}"

rm -rf build/artifact
mkdir -p build/artifact/bin build/artifact/extensions build/artifact/logs

install -m 0755 build/release/duckdb build/artifact/bin/duckdb
install -m 0755 build/release/test/unittest build/artifact/bin/unittest

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
  echo "compiled_extension=qa_test"
} | tee build/artifact/logs/build-info.txt

build/artifact/bin/duckdb --version
build/artifact/bin/unittest --help >/dev/null
