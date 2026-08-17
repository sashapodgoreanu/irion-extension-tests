from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_DUCKDB_PROXY = REPOSITORY_ROOT / "scripts" / "windows-duckdb-proxy.sh"


class WindowsDuckDBProxyTestCase(unittest.TestCase):
    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    def test_inline_command_does_not_consume_orchestration_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = root / "runtime-helper.sh"
            helper.write_text(
                """#!/usr/bin/env bash
qa_prepare_native_windows_call() { :; }
qa_finish_native_windows_call() { :; }
qa_translate_windows_text() { printf '%s' "$1"; }
""",
                encoding="utf-8",
            )

            fake_duckdb = root / "duckdb.exe"
            fake_duckdb.write_text(
                """#!/usr/bin/env bash
if IFS= read -r unexpected; then
  printf 'consumed:%s\\n' "$unexpected" >&2
  exit 99
fi
printf 'args:%s\\n' "$*"
""",
                encoding="utf-8",
            )
            fake_duckdb.chmod(0o755)

            env = dict(os.environ)
            env["QA_WSL_RUNTIME_HELPER"] = str(helper)
            env["QA_WINDOWS_DUCKDB_EXE"] = str(fake_duckdb)

            result = subprocess.run(
                ["bash", str(WINDOWS_DUCKDB_PROXY), "-c", "SELECT 1"],
                cwd=REPOSITORY_ROOT,
                env=env,
                input="proxy|squid|3128\nproxy-auth|squid|3129\n",
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("consumed:", result.stderr)
            self.assertIn("args:-c SELECT 1", result.stdout)

    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    def test_non_inline_call_preserves_redirected_fixture_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = root / "runtime-helper.sh"
            helper.write_text(
                """#!/usr/bin/env bash
qa_prepare_native_windows_call() { :; }
qa_finish_native_windows_call() { :; }
qa_translate_windows_text() { printf '%s' "$1"; }
""",
                encoding="utf-8",
            )

            fake_duckdb = root / "duckdb.exe"
            fake_duckdb.write_text(
                """#!/usr/bin/env bash
IFS= read -r sql || exit 98
printf 'stdin:%s\\n' "$sql"
printf 'args:%s\\n' "$*"
""",
                encoding="utf-8",
            )
            fake_duckdb.chmod(0o755)

            env = dict(os.environ)
            env["QA_WSL_RUNTIME_HELPER"] = str(helper)
            env["QA_WINDOWS_DUCKDB_EXE"] = str(fake_duckdb)

            result = subprocess.run(
                ["bash", str(WINDOWS_DUCKDB_PROXY), "attach.db"],
                cwd=REPOSITORY_ROOT,
                env=env,
                input="CREATE TABLE integral_values(i INTEGER);\n",
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "stdin:CREATE TABLE integral_values(i INTEGER);", result.stdout
            )
            self.assertIn("args:attach.db", result.stdout)


if __name__ == "__main__":
    unittest.main()
