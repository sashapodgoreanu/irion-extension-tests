from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RESOLVER = REPOSITORY_ROOT / "scripts" / "prepare-runner-matrices.py"
EXTENSIONS = REPOSITORY_ROOT / "config" / "extensions.yml"
RUNNERS = REPOSITORY_ROOT / "config" / "runners.yml"
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "extension-qa.yml"
WSL_RUNTIME = REPOSITORY_ROOT / "scripts" / "windows-wsl-runtime.py"
WSL_HELPER = REPOSITORY_ROOT / "scripts" / "windows-wsl-runtime.sh"
WINDOWS_DUCKDB_PROXY = REPOSITORY_ROOT / "scripts" / "windows-duckdb-proxy.sh"
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

    def test_windows_batteries_finish_before_linux_batteries_start(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        # Builds intentionally remain independent and may execute in parallel.
        self.assertIn("  build-linux:\n    name: Build Linux", workflow)
        self.assertIn("  build-windows:\n    name: Build Windows", workflow)
        self.assertIn("  build-linux:\n    name: Build Linux ${{ needs.configure.outputs.duckdb_version }}\n    needs: configure", workflow)
        self.assertIn("  build-windows:\n    name: Build Windows ${{ needs.configure.outputs.duckdb_version }}\n    needs: configure", workflow)

        # Windows gets first access to shared cloud accounts. Linux waits for the
        # Windows matrix to settle, but still runs when Windows tests fail.
        self.assertIn(
            "  test-windows:\n    name: ${{ matrix.name }}\n    needs: build-windows",
            workflow,
        )
        self.assertIn(
            "  test-linux:\n    name: ${{ matrix.name }}\n    needs:\n      - build-linux\n      - test-windows",
            workflow,
        )
        self.assertIn(
            "needs.test-windows.result != 'cancelled'",
            workflow,
        )
        self.assertIn("same external cloud accounts and resources", workflow)

        # Aggregation is artifact-only, so both final summaries may run in
        # parallel once the Linux matrix (and transitively Windows) has settled.
        self.assertIn(
            "  aggregate-linux:\n    name: Aggregate Linux results\n    needs: test-linux",
            workflow,
        )
        self.assertIn(
            "  aggregate-windows:\n    name: Aggregate Windows results\n    needs:\n      - test-windows\n      - test-linux",
            workflow,
        )

    def test_windows_wsl_argument_bridge_preserves_cli_payloads(self) -> None:
        environment = os.environ.copy()
        environment["QA_WSL_RUNTIME_PY"] = str(WSL_RUNTIME)
        shell = f'source "{WSL_HELPER}"; qa_translate_windows_text "$1"'

        cases = {
            "-csv": "-csv",
            "": "",
            "ATTACH '/mnt/d/a/test.duckdb'": "ATTACH 'D:/a/test.duckdb'",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                result = subprocess.run(
                    ["bash", "-c", shell, "qa-bridge", source],
                    cwd=REPOSITORY_ROOT,
                    env=environment,
                    check=True,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.stdout, expected)

    def test_windows_duckdb_proxy_translates_stdin_only_when_opted_in(self) -> None:
        text = WINDOWS_DUCKDB_PROXY.read_text(encoding="utf-8")
        self.assertIn('QA_DUCKDB_TRANSLATE_STDIN:-0', text)
        self.assertIn('translate-stdin', text)
        self.assertIn('has_inline_command', text)


if __name__ == "__main__":
    unittest.main()
