from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_UNITTEST_PROXY = REPOSITORY_ROOT / "scripts" / "windows-unittest-proxy.sh"


class WindowsUnitTestProxyTestCase(unittest.TestCase):
    def run_proxy(self, listing: str, *arguments: str) -> subprocess.CompletedProcess[str]:
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

            fake_unittest = root / "unittest.exe"
            fake_unittest.write_text(
                """#!/usr/bin/env bash
if [[ "$1" == "-l" || "$1" == "--list-tests" ]]; then
  printf '%s' "$QA_TEST_LISTING"
else
  printf 'args:%s\\n' "$*"
fi
""",
                encoding="utf-8",
            )
            fake_unittest.chmod(0o755)

            env = dict(os.environ)
            env["QA_WSL_RUNTIME_HELPER"] = str(helper)
            env["QA_WSL_RUNTIME_PY"] = "unused-unless-config-is-translated"
            env["QA_WINDOWS_UNITTEST_EXE"] = str(fake_unittest)
            env["QA_TEST_LISTING"] = listing

            return subprocess.run(
                ["bash", str(WINDOWS_UNITTEST_PROXY), *arguments],
                cwd=REPOSITORY_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )

    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    def test_header_only_listing_is_reported_as_no_embedded_tests(self) -> None:
        result = self.run_proxy("name\tgroup\r\n", "-l")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("no embedded tests to list", result.stderr)

    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    def test_real_listing_rows_are_passed_through_unchanged(self) -> None:
        listing = "name\tgroup\r\nsql_logic_test\t[test]\r\n"
        result = self.run_proxy(listing, "-l")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, listing.replace("\r\n", "\n"))

    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    def test_regular_invocations_are_not_treated_as_listings(self) -> None:
        result = self.run_proxy("", "--test-dir", "test")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("args:--test-dir test", result.stdout)


if __name__ == "__main__":
    unittest.main()
