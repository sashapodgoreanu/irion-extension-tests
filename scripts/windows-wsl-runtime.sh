#!/usr/bin/env bash
# Shared helpers for invoking native Windows DuckDB binaries from the WSL QA host.

set -Eeuo pipefail

: "${QA_WSL_RUNTIME_PY:?QA_WSL_RUNTIME_PY is required}"

qa_wslenv_add() {
  local name=$1
  local mode=${2:-}
  local entry="${name}${mode}"
  case ":${WSLENV:-}:" in
    *":${entry}:"*) ;;
    *) export WSLENV="${WSLENV:+${WSLENV}:}${entry}" ;;
  esac
}

qa_is_path_variable() {
  case "$1" in
    HOME|USERPROFILE|TEMP|TMP|TMPDIR|LOCAL_EXTENSION_REPO|GOOGLE_APPLICATION_CREDENTIALS|BQ_TEST_SA_KEY_PATH|PGSCANNERTMP_ABS_DIR_PREFIX|PYTHON_HTTP_SERVER_DIR|GOLDEN_TABLES_PATH|DELTA_KERNEL_TESTS_PATH|DAT_PATH)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

qa_should_forward_variable() {
  case "$1" in
    HOME|USERPROFILE|TEMP|TMP|TMPDIR|LOCAL_EXTENSION_REPO|\
    BQ_*|GOOGLE_*|PG*|POSTGRES_*|MSSQL_*|AWS_*|S3_*|DUCKDB_*|\
    AZURE_*|AZ_*|HTTP_*|HTTPS_*|PYTHON_*|UC_*|UNITY_*|TEST_*|\
    ENABLE_*|GENERATED_*|GOLDEN_*|DELTA_*|DAT_*|FIXTURE_*|VENDED_*|EQUALITY_*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

qa_prepare_windows_environment() {
  export USERPROFILE="${HOME}"
  export TEMP="${TMPDIR:-${TEMP:-${HOME}/tmp}}"
  export TMP="${TMPDIR:-${TMP:-${TEMP}}}"

  local name
  while IFS= read -r name; do
    qa_should_forward_variable "${name}" || continue
    if qa_is_path_variable "${name}"; then
      qa_wslenv_add "${name}" "/p"
    else
      qa_wslenv_add "${name}"
    fi
  done < <(compgen -e)
}

qa_sync_directory() {
  local source=$1
  local destination=$2
  [[ -d "${source}" ]] || return 0
  mkdir -p "${destination}"
  rsync -a --delete "${source}/" "${destination}/"
}

qa_extension_home_root() {
  printf '%s/.duckdb/extensions/%s' "${HOME}" "${DUCKDB_VERSION:?DUCKDB_VERSION is required}"
}

qa_sync_linux_extensions_to_windows() {
  local root
  root="$(qa_extension_home_root)"
  qa_sync_directory "${root}/linux_amd64" "${root}/windows_amd64"
}

qa_sync_windows_extensions_to_linux() {
  local root
  root="$(qa_extension_home_root)"
  qa_sync_directory "${root}/windows_amd64" "${root}/linux_amd64"
}

qa_sync_local_repository_to_windows() {
  [[ -n "${LOCAL_EXTENSION_REPO:-}" ]] || return 0
  local version="${DUCKDB_VERSION:?DUCKDB_VERSION is required}"
  qa_sync_directory \
    "${LOCAL_EXTENSION_REPO}/${version}/linux_amd64" \
    "${LOCAL_EXTENSION_REPO}/${version}/windows_amd64"
}

qa_prepare_native_windows_call() {
  command -v rsync >/dev/null 2>&1 || {
    echo "Windows WSL runtime bridge requires rsync" >&2
    return 1
  }
  qa_prepare_windows_environment
  qa_sync_linux_extensions_to_windows
  qa_sync_local_repository_to_windows
}

qa_finish_native_windows_call() {
  qa_sync_windows_extensions_to_linux
}

qa_translate_windows_text() {
  python3 "${QA_WSL_RUNTIME_PY}" translate-text "$1"
}
