#!/usr/bin/env bash
set -Eeuo pipefail

: "${QA_WSL_RUNTIME_HELPER:?QA_WSL_RUNTIME_HELPER is required}"
: "${QA_WSL_RUNTIME_PY:?QA_WSL_RUNTIME_PY is required}"
: "${QA_WINDOWS_UNITTEST_EXE:?QA_WINDOWS_UNITTEST_EXE is required}"
# shellcheck disable=SC1090
source "${QA_WSL_RUNTIME_HELPER}"

qa_prepare_native_windows_call

translated=()
while (($#)); do
  case "$1" in
    --test-config)
      [[ $# -ge 2 ]] || { echo "--test-config requires a path" >&2; exit 2; }
      source_config=$2
      windows_config="${source_config}.windows.json"
      python3 "${QA_WSL_RUNTIME_PY}" translate-config "${source_config}" "${windows_config}"
      translated+=("--test-config" "$(qa_translate_windows_text "${windows_config}")")
      shift 2
      ;;
    --test-config=*)
      source_config=${1#--test-config=}
      windows_config="${source_config}.windows.json"
      python3 "${QA_WSL_RUNTIME_PY}" translate-config "${source_config}" "${windows_config}"
      translated+=("--test-config=$(qa_translate_windows_text "${windows_config}")")
      shift
      ;;
    *)
      translated+=("$(qa_translate_windows_text "$1")")
      shift
      ;;
  esac
done

set +e
"${QA_WINDOWS_UNITTEST_EXE}" "${translated[@]}"
status=$?
set -e

sync_status=0
qa_finish_native_windows_call || sync_status=$?
if [[ "${status}" -eq 0 && "${sync_status}" -ne 0 ]]; then
  status="${sync_status}"
fi
exit "${status}"
