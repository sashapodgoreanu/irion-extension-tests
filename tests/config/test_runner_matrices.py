from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RESOLVER = REPOSITORY_ROOT / "scripts" / "prepare-runner-matrices.py"
EXTENSIONS = REPOSITORY_ROOT / "config" / "extensions.yml"
RUNNERS = REPOSITORY_ROOT / "config" / "runners.yml"
EXPECTED = [
    "httpfs",
    "ducklake",
    "postgres_scanner",
    "delta",
    "iceberg",
    "azure",
    "unity_catalog",
    "bigquery",
    "mssql",
    "irion",
]


class RunnerMatricesTestCase(unittest.TestCase):
    def test_linux_and_windows_receive_the_same_batteries(self) -> None:
        result = subprocess.run(
            [sys.executable, str(RESOLVER), str(EXTENSIONS), str(RUNNERS)],
            cwd=REPOSITORY_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        outputs = dict(
            line.split("=", 1)
            for line in result.stdout.splitlines()
            if "=" in line
        )
        linux = json.loads(outputs["linux_matrix"])["include"]
        windows = json.loads(outputs["windows_matrix"])["include"]

        self.assertEqual([item["name"] for item in linux], EXPECTED)
        self.assertEqual([item["name"] for item in windows], EXPECTED)
        self.assertEqual(
            [item["name"] for item in linux],
            [item["name"] for item in windows],
        )
        self.assertTrue(all(item["runtime"]["operatingSystem"] == "linux" for item in linux))
        self.assertTrue(all(item["runtime"]["operatingSystem"] == "windows" for item in windows))
        self.assertTrue(all(item["runtime"]["architecture"] == "x86_64" for item in windows))
        self.assertEqual(outputs["linux_enabled"], "true")
        self.assertEqual(outputs["windows_enabled"], "true")


if __name__ == "__main__":
    unittest.main()
