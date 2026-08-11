from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RESULT_WRITER = REPOSITORY_ROOT / "scripts" / "write-test-result.py"


def battery() -> dict:
    return {
        "name": "reporting_test",
        "runner": "standard",
        "sourceType": "self",
        "duckdbVersion": "v1.5.5",
        "runtime": {
            "duckdbVersion": "v1.5.5",
            "ciToolsVersion": "v1.5.5",
            "operatingSystem": "windows",
            "architecture": "x86_64",
            "githubRunner": "windows-latest",
        },
        "capabilities": [],
        "prerequisites": [],
        "services": [],
        "extensions": [{"name": "qa_test"}],
        "profiles": [{"name": "sql", "tests": "test/sql/*", "services": []}],
        "ignoredTests": [],
    }


class ResultWriterReportingTestCase(unittest.TestCase):
    def invoke_writer(
        self,
        root: Path,
        *,
        exit_code: int,
        preserve_existing: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        config = root / "battery.json"
        log_dir = root / "logs"
        output = root / "results" / "result.json"
        config.write_text(json.dumps(battery()), encoding="utf-8")
        log_dir.mkdir(parents=True, exist_ok=True)

        command = [
            sys.executable,
            str(RESULT_WRITER),
            "--battery-config",
            str(config),
            "--log-dir",
            str(log_dir),
            "--output",
            str(output),
            "--exit-code",
            str(exit_code),
            "--reason",
            "test-battery-failed" if exit_code else "",
        ]
        if preserve_existing:
            command.append("--preserve-existing")
        return subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
        )

    def test_default_writer_still_propagates_failed_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed = self.invoke_writer(root, exit_code=1)
            self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads((root / "results" / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "failed")

    def test_reporting_finalizer_writes_failed_result_but_returns_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed = self.invoke_writer(root, exit_code=1, preserve_existing=True)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads((root / "results" / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "failed")

    def test_reporting_finalizer_preserves_existing_failed_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.invoke_writer(root, exit_code=1)
            self.assertNotEqual(first.returncode, 0)
            before = (root / "results" / "result.json").read_text(encoding="utf-8")

            second = self.invoke_writer(root, exit_code=0, preserve_existing=True)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            after = (root / "results" / "result.json").read_text(encoding="utf-8")
            self.assertEqual(after, before)
            self.assertIn("Preserving structured result", second.stdout)


if __name__ == "__main__":
    unittest.main()
