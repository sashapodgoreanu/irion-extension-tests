#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "scripts/service-manager.sh",
    '''  mkdir -p "${QA_SERVICE_LOG_DIR}/${name}"
  (
    cd "${QA_SERVICE_UPSTREAM_ROOT}"
    ./scripts/run_squid.sh \\
      --port "${port}" \\
      --log_dir "${QA_SERVICE_LOG_DIR}/${name}"
  ) >"${QA_SERVICE_LOG_DIR}/${name}-process.log" 2>&1 &''',
    '''  local log_dir="${QA_SERVICE_LOG_DIR}/${name}"

  # Ubuntu packages may start a system Squid instance. The upstream HTTPFS
  # helper uses a process-global shared-memory name, so stop the packaged
  # service and remove stale IPC state before starting the isolated proxy.
  sudo systemctl stop squid >/dev/null 2>&1 \\
    || sudo service squid stop >/dev/null 2>&1 \\
    || true
  sudo rm -f /dev/shm/squid-* >/dev/null 2>&1 || true

  # run_squid.sh intentionally creates log_dir with plain `mkdir`; do not
  # pre-create it here. Remove only the job-local directory from prior attempts.
  rm -rf "${log_dir}"
  (
    cd "${QA_SERVICE_UPSTREAM_ROOT}"
    ./scripts/run_squid.sh \\
      --port "${port}" \\
      --log_dir "${log_dir}"
  ) >"${QA_SERVICE_LOG_DIR}/${name}-process.log" 2>&1 &''',
)

replace_once(
    "tests/config/test_profiles_runtime.py",
    '''    def test_service_manager_rejects_unknown_runtime_service(self) -> None:
''',
    '''    def test_squid_service_preserves_upstream_directory_and_ipc_contract(self) -> None:
        script = SERVICE_MANAGER.read_text(encoding="utf-8")
        self.assertNotIn('mkdir -p "${QA_SERVICE_LOG_DIR}/${name}"', script)
        self.assertIn("sudo systemctl stop squid", script)
        self.assertIn("sudo rm -f /dev/shm/squid-*", script)
        self.assertIn('rm -rf "${log_dir}"', script)
        self.assertIn('--log_dir "${log_dir}"', script)

    def test_service_manager_rejects_unknown_runtime_service(self) -> None:
''',
)

(ROOT / "scripts/apply-httpfs-squid-lifecycle-fix.py").unlink()
