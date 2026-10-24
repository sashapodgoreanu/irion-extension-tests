"""Guard the generated MSSQL release runner against malformed Bash syntax."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATCHER = ROOT / "scripts" / "prepare-mssql-configured-runner.py"
SOURCE = ROOT / "scripts" / "run-mssql-tests-base.sh"


class MSSQLGeneratedRunnerSyntaxTests(unittest.TestCase):
    def test_duckdb_two_mssql_runner_is_valid_bash(self) -> None:
        # Exercise the actual source-to-runner transformation before spinning up
        # SQL Server. A previously truncated grep guard made this fail at line 379.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "run-mssql-tests-base.sh"
            generated = subprocess.run(
                [sys.executable, str(PATCHER), str(SOURCE), str(target), "v2.0.0"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)
            check = subprocess.run(
                ["bash", "-n", str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(check.returncode, 0, check.stderr)
            script = target.read_text(encoding="utf-8")
            self.assertEqual(script.count("if grep -Eq '^require-env (MSSQL_TEST_DSN"), 1)
            self.assertEqual(script.count("if grep -Eq '^require mssql:"), 1)
            self.assertEqual(script.count("if ! grep -Eq '([1-9]"), 1)
            self.assertNotIn('"skip_tests": [', script)
            self.assertIn('--keep-home', script)
            self.assertIn('DUCKDB_VERSION_DIRECTORY="${DUCKDB_VERSION:-v2.0.0}"', script)
            self.assertIn("SQL Server service is not ready", script)


if __name__ == "__main__":
    unittest.main()
