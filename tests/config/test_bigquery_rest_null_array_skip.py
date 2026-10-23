from __future__ import annotations

import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "skip-bigquery-rest-null-array-test.py"
DATA = runpy.run_path(str(TOOL))
CASE = DATA["EXPECTED_BLOCK"]
SKIP = DATA["SKIP_COMMENT"]


class TestBigQueryNullArrayCase(unittest.TestCase):
    def checkout(self, root: Path, *, corrupt: bool = False) -> tuple[Path, Path]:
        upstream = root / "upstream"
        path = upstream / "test/sql/functions/function_bigquery_query_rest.test"
        path.parent.mkdir(parents=True)
        target = CASE.replace("SELECT [1, NULL, 3]", "SELECT [1, NULL, 2]") if corrupt else CASE
        path.write_text(
            "query I\nSELECT 42;\n----\n42\n\n"
            + target
            + "\n\nstatement ok\nSET bq_debug_show_queries = false;\n",
            encoding="utf-8",
        )
        return upstream, path

    def run_tool(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(TOOL), str(root)],
                              capture_output=True, text=True)

    def test_skips_only_one_statement_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, path = self.checkout(Path(tmp))
            result = self.run_tool(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = path.read_text(encoding="utf-8")
            self.assertIn(SKIP, updated)
            self.assertNotIn("SELECT [1, NULL, 3] AS arr", updated)
            self.assertIn("SELECT 42;", updated)
            self.assertIn("SET bq_debug_show_queries = false;", updated)
            self.assertEqual(self.run_tool(root).returncode, 0)
            self.assertEqual(path.read_text(encoding="utf-8"), updated)

    def test_changed_upstream_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, path = self.checkout(Path(tmp), corrupt=True)
            original = path.read_text(encoding="utf-8")
            result = self.run_tool(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("expected 1", result.stderr)
            self.assertEqual(original, path.read_text(encoding="utf-8"))

    def test_linux_and_windows_runners_call_local_skip(self) -> None:
        shell = (ROOT / "scripts/run-test-battery.sh").read_text(encoding="utf-8")
        native = (ROOT / "scripts/run-standard-tests.py").read_text(encoding="utf-8")
        self.assertIn("skip-bigquery-rest-null-array-test.py", shell)
        self.assertIn("skip-bigquery-rest-null-array-test.py", native)


if __name__ == "__main__":
    unittest.main()
