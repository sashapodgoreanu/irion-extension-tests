from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

import yaml
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RESOLVER = REPOSITORY_ROOT / "scripts" / "prepare-runner-matrices.py"
EXTENSIONS = REPOSITORY_ROOT / "config" / "extensions.yml"
RUNNERS = REPOSITORY_ROOT / "config" / "runners.yml"
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "extension-qa.yml"
LINUX_WORKFLOW = WORKFLOW.with_name("qa-linux.yml")
WINDOWS_WORKFLOW = WORKFLOW.with_name("qa-windows.yml")
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
    "irion_extension_security",
]


class RunnerMatricesTestCase(unittest.TestCase):
    def test_enabled_runners_receive_the_full_battery_matrix(self) -> None:
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

        self.assertEqual(outputs["enabled_batteries"].split(","), EXPECTED)

        matrices = {
            "linux": linux,
            "windows": windows,
        }
        for runner_name, matrix in matrices.items():
            enabled = outputs[f"{runner_name}_enabled"] == "true"
            names = [item["name"] for item in matrix]
            self.assertEqual(names, EXPECTED if enabled else [])
            if enabled:
                self.assertTrue(
                    all(
                        item["runtime"]["operatingSystem"] == runner_name
                        for item in matrix
                    )
                )
                self.assertTrue(
                    all(item["runtime"]["architecture"] == "x86_64" for item in matrix)
                )

        if outputs["linux_enabled"] == "true" and outputs["windows_enabled"] == "true":
            self.assertEqual(
                [item["name"] for item in linux],
                [item["name"] for item in windows],
            )

    def test_battery_filter_selects_only_requested_batteries(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(RESOLVER),
                str(EXTENSIONS),
                str(RUNNERS),
                "--batteries",
                "irion_extension_security",
            ],
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
        self.assertEqual(outputs["enabled_batteries"], "irion_extension_security")
        for runner_name in ("linux", "windows"):
            matrix = json.loads(outputs[f"{runner_name}_matrix"])["include"]
            expected = (
                ["irion_extension_security"]
                if outputs[f"{runner_name}_enabled"] == "true"
                else []
            )
            self.assertEqual([item["name"] for item in matrix], expected)

    def test_platform_filter_disables_unselected_runner(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(RESOLVER),
                str(EXTENSIONS),
                str(RUNNERS),
                "--batteries",
                "irion_extension_security",
                "--platforms",
                "linux",
            ],
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
        self.assertEqual(outputs["enabled_batteries"], "irion_extension_security")
        self.assertEqual(outputs["linux_enabled"], "true")
        self.assertEqual(outputs["windows_enabled"], "false")
        self.assertEqual(
            [item["name"] for item in json.loads(outputs["linux_matrix"])["include"]],
            ["irion_extension_security"],
        )
        self.assertEqual(json.loads(outputs["windows_matrix"])["include"], [])

    def test_platform_filter_can_enable_a_configured_disabled_runner(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(RESOLVER),
                str(EXTENSIONS),
                str(RUNNERS),
                "--batteries",
                "irion_extension_security",
                "--platforms",
                "windows",
            ],
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
        self.assertEqual(outputs["linux_enabled"], "false")
        self.assertEqual(outputs["windows_enabled"], "true")
        self.assertEqual(json.loads(outputs["linux_matrix"])["include"], [])
        self.assertEqual(
            [item["name"] for item in json.loads(outputs["windows_matrix"])["include"]],
            ["irion_extension_security"],
        )

    def test_filters_reject_unknown_values(self) -> None:
        for flag, value in (("--batteries", "missing"), ("--platforms", "macos")):
            with self.subTest(flag=flag):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(RESOLVER),
                        str(EXTENSIONS),
                        str(RUNNERS),
                        flag,
                        value,
                    ],
                    cwd=REPOSITORY_ROOT,
                    check=False,
                    text=True,
                    capture_output=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unknown", result.stderr.lower())

    def test_separate_platform_workflows_have_isolated_jobs(self) -> None:
        def read_yaml(path: Path) -> dict:
            # Preserve the YAML 1.1 "on" key when parsing workflow files.
            return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

        entry = read_yaml(WORKFLOW)
        linux = read_yaml(LINUX_WORKFLOW)
        windows = read_yaml(WINDOWS_WORKFLOW)
        self.assertEqual(set(entry["jobs"]), {"configure", "windows", "linux"})
        self.assertEqual(entry["jobs"]["windows"]["needs"], "configure")
        self.assertEqual(entry["jobs"]["linux"]["needs"], ["configure", "windows"])
        self.assertIn("always()", entry["jobs"]["linux"]["if"])
        self.assertIn("needs.configure.result == 'success'", entry["jobs"]["linux"]["if"])
        self.assertEqual(entry["jobs"]["windows"]["secrets"], "inherit")
        self.assertEqual(entry["jobs"]["linux"]["secrets"], "inherit")

        for os, child in (("windows", windows), ("linux", linux)):
            with self.subTest(platform=os):
                self.assertEqual(
                    entry["jobs"][os]["uses"],
                    f"./.github/workflows/qa-{os}.yml",
                )
                self.assertIn("workflow_call", child["on"])
                self.assertEqual(
                    set(child["on"]["workflow_call"]["inputs"]),
                    {
                        "matrix", "duckdb_version", "ci_tools_version",
                        "operating_system", "architecture", "github_runner",
                    },
                )
                self.assertEqual(
                    set(child["jobs"]),
                    {f"build-{os}", f"test-{os}", f"aggregate-{os}"},
                )
                self.assertEqual(
                    child["jobs"][f"build-{os}"]["runs-on"],
                    "${{ inputs.github_runner }}",
                )
                self.assertEqual(child["jobs"][f"test-{os}"]["needs"], f"build-{os}")
                self.assertEqual(child["jobs"][f"aggregate-{os}"]["needs"], f"test-{os}")
                self.assertNotIn("needs.configure", str(child["jobs"]))
                self.assertNotIn(
                    f"needs.test-{'linux' if os == 'windows' else 'windows'}",
                    str(child["jobs"]),
                )
                self.assertEqual(
                    child["jobs"][f"test-{os}"]["strategy"]["matrix"],
                    "${{ fromJSON(needs.build-" + os + ".outputs.matrix) }}",
                )

    def test_child_workflows_use_one_shared_matrix_and_pin_source(self) -> None:
        entry = WORKFLOW.read_text(encoding="utf-8")
        for shared in (
            "scripts/prepare-runner-matrices.py",
            "config/extensions.yml",
            "config/runners.yml",
        ):
            self.assertIn(shared, entry)
        for child in (LINUX_WORKFLOW, WINDOWS_WORKFLOW):
            content = child.read_text(encoding="utf-8")
            self.assertIn("repository: ${{ matrix.repository }}", content)
            self.assertIn("ref: ${{ matrix.pin }}", content)
            self.assertNotIn("scripts/prepare-runner-matrices.py", content)

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
