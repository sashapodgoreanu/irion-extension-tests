from __future__ import annotations

import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEGACY = "<REGEX>:[a-zA-Z0-9]+"
CURRENT = "<REGEX>:[a-zA-Z0-9-]+"


class Logger:
    def info(self, message: str) -> None:
        pass


class TestBigQueryAdaptation(unittest.TestCase):
    def make_fixture(self, root: Path, old: bool) -> Path:
        upstream = root / "upstream"
        sql = upstream / "test" / "sql"
        (sql / "storage").mkdir(parents=True)
        (sql / "functions").mkdir()
        (sql / "misc").mkdir()
        (sql / "storage" / "attach_public_dataset.test").write_text(
            "require bigquery\nSELECT billing_project=${BQ_TEST_BILLING_PROJECT};\n",
            encoding="utf-8",
        )
        (sql / "functions" / "function_bigquery_jobs.test").write_text(
            "require bigquery\n" + (LEGACY if old else CURRENT) + "\n",
            encoding="utf-8",
        )
        (sql / "misc" / "location.test").write_text(
            "require bigquery\nSELECT 'europe-west3';\n", encoding="utf-8"
        )
        return upstream

    def validate(self, root: Path) -> None:
        files = {
            path.name: path.read_text(encoding="utf-8")
            for path in (root / "test" / "sql").rglob("*.test")
        }
        self.assertEqual(len(files), 3)
        self.assertTrue(all("require bigquery" not in s for s in files.values()))
        self.assertIn(CURRENT, files["function_bigquery_jobs.test"])
        self.assertIn(
            "billing_project='${BQ_TEST_BILLING_PROJECT}'",
            files["attach_public_dataset.test"],
        )
        self.assertIn("'EU'", files["location.test"])

    def test_bash_adapter_accepts_old_and_current_regex(self) -> None:
        s = (ROOT / "scripts" / "run-test-battery.sh").read_text(encoding="utf-8")
        start_func = s.index("prepare_bigquery_dynamic_tests() {")
        marker = "python3 - " + chr(34) + "${UPSTREAM_ROOT}" + chr(34) + " <<'PY'"
        start = s.index(marker, start_func) + len(marker)
        source = s[start:s.index("\nPY\n}", start)].lstrip("\n")
        for old in (True, False):
            with self.subTest(old=old), tempfile.TemporaryDirectory() as tmp:
                upstream = self.make_fixture(Path(tmp), old)
                subprocess.run(
                    [sys.executable, "-c", source, str(upstream)],
                    check=True, capture_output=True, text=True
                )
                self.validate(upstream)

    def test_native_adapter_accepts_old_and_current_regex(self) -> None:
        runner = runpy.run_path(str(ROOT / "scripts" / "run-standard-tests.py"))
        for old in (True, False):
            with self.subTest(old=old), tempfile.TemporaryDirectory() as tmp:
                upstream = self.make_fixture(Path(tmp), old)
                runner["adapt_bigquery_tests"](upstream, Logger())
                self.validate(upstream)


if __name__ == "__main__":
    unittest.main()
