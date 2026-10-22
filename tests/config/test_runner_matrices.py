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
LINUX_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "qa-linux.yml"
WINDOWS_WORKFLOW = LINUX_WORKFLOW.with_name("qa-windows.yml")
LEGACY_WORKFLOW = LINUX_WORKFLOW.with_name("extension-qa.yml")
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

    def test_two_standalone_platform_workflows(self) -> None:
        def load(path: Path) -> dict:
            return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

        self.assertFalse(LEGACY_WORKFLOW.exists())
        for platform, path in (("linux", LINUX_WORKFLOW), ("windows", WINDOWS_WORKFLOW)):
            with self.subTest(platform=platform):
                workflow = load(path)
                self.assertEqual(set(workflow["on"]), {"pull_request", "workflow_dispatch"})
                self.assertEqual(
                    set(workflow["jobs"]),
                    {"configure", f"build-{platform}", f"test-{platform}",
                     f"aggregate-{platform}"},
                )
                self.assertEqual(workflow["jobs"][f"build-{platform}"]["needs"], "configure")
                self.assertEqual(workflow["jobs"][f"test-{platform}"]["needs"], f"build-{platform}")
                self.assertEqual(workflow["jobs"][f"aggregate-{platform}"]["needs"], f"test-{platform}")
                self.assertEqual(
                    workflow["jobs"][f"build-{platform}"]["runs-on"],
                    "${{ needs.configure.outputs.github_runner }}",
                )
                self.assertEqual(
                    workflow["jobs"][f"test-{platform}"]["strategy"]["matrix"],
                    "${{ fromJSON(needs.build-" + platform + ".outputs.matrix) }}",
                )
                self.assertIn(
                    "--platforms " + platform,
                    workflow["jobs"]["configure"]["steps"][2]["run"],
                )
                self.assertNotIn("workflow_call", workflow["on"])
                self.assertNotIn("uses: ./.github/workflows/", path.read_text())
                other = "windows" if platform == "linux" else "linux"
                self.assertNotIn("needs.test-" + other, path.read_text())

    def test_os_workflow_concurrency_is_not_shared(self) -> None:
        # Both OS workflows can run concurrently; only duplicate runs of the
        # same workflow/ref share the normal GitHub Actions concurrency queue.
        groups = []
        for path in (LINUX_WORKFLOW, WINDOWS_WORKFLOW):
            workflow = yaml.load(
                path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
            )
            group = workflow["concurrency"]["group"]
            self.assertEqual(group, "${{ github.workflow }}-${{ github.ref }}")
            self.assertEqual(workflow["concurrency"]["cancel-in-progress"], "false")
            self.assertNotIn("extension-qa-cloud-", group)
            groups.append(workflow["name"])
        self.assertEqual(len(set(groups)), 2)

    def test_platform_pipelines_resolve_shared_battery_pins(self) -> None:
        for path in (LINUX_WORKFLOW, WINDOWS_WORKFLOW):
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertIn("scripts/prepare-runner-matrices.py", source)
                self.assertIn("config/extensions.yml", source)
                self.assertIn("config/runners.yml", source)
                self.assertIn("repository: ${{ matrix.repository }}", source)
                self.assertIn("ref: ${{ matrix.pin }}", source)
                self.assertIn("qa-execution-plan", source)

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
