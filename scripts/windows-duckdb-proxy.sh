#!/usr/bin/env bash
set -Eeuo pipefail

: "${QA_WSL_RUNTIME_HELPER:?QA_WSL_RUNTIME_HELPER is required}"
: "${QA_WINDOWS_DUCKDB_EXE:?QA_WINDOWS_DUCKDB_EXE is required}"
# shellcheck disable=SC1090
source "${QA_WSL_RUNTIME_HELPER}"

qa_prepare_native_windows_call

translated=()
for argument in "$@"; do
  translated+=("$(qa_translate_windows_text "${argument}")")
done

set +e
"${QA_WINDOWS_DUCKDB_EXE}" "${translated[@]}"
status=$?
set -e

sync_status=0
qa_finish_native_windows_call || sync_status=$?
if [[ "${status}" -eq 0 && "${sync_status}" -ne 0 ]]; then
  status="${sync_status}"
fi
exit "${status}"
