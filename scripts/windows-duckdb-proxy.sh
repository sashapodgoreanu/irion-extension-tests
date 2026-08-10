#!/usr/bin/env bash
set -Eeuo pipefail

: "${QA_WSL_RUNTIME_HELPER:?QA_WSL_RUNTIME_HELPER is required}"
: "${QA_WINDOWS_DUCKDB_EXE:?QA_WINDOWS_DUCKDB_EXE is required}"
# shellcheck disable=SC1090
source "${QA_WSL_RUNTIME_HELPER}"

qa_prepare_native_windows_call

translated=()
has_inline_command=0
for argument in "$@"; do
  case "${argument}" in
    -c|--command|--command=*) has_inline_command=1 ;;
  esac
  translated+=("$(qa_translate_windows_text "${argument}")")
done

translated_input=""
cleanup() {
  [[ -z "${translated_input}" ]] || rm -f "${translated_input}"
}
trap cleanup EXIT

set +e
if [[ "${QA_DUCKDB_TRANSLATE_STDIN:-0}" == "1" && "${has_inline_command}" == "0" ]]; then
  translated_input="$(mktemp)"
  python3 "${QA_WSL_RUNTIME_PY}" translate-stdin >"${translated_input}"
  translate_status=$?
  if [[ "${translate_status}" -ne 0 ]]; then
    status="${translate_status}"
  else
    "${QA_WINDOWS_DUCKDB_EXE}" "${translated[@]}" <"${translated_input}"
    status=$?
  fi
else
  "${QA_WINDOWS_DUCKDB_EXE}" "${translated[@]}"
  status=$?
fi
set -e

sync_status=0
qa_finish_native_windows_call || sync_status=$?
if [[ "${status}" -eq 0 && "${sync_status}" -ne 0 ]]; then
  status="${sync_status}"
fi
exit "${status}"
