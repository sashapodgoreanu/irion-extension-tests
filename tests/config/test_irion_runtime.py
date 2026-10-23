from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from qa import load_config, resolve_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPOSITORY_ROOT / "config" / "extensions.yml"
PROFILE_PREPARER = REPOSITORY_ROOT / "scripts" / "prepare-standard-profile.py"
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "qa-linux.yml"
WINDOWS_BATTERY_RUNNER = REPOSITORY_ROOT / "scripts" / "run-windows-wsl-battery.ps1"
SECURITY_TEST = REPOSITORY_ROOT / "test" / "sql" / "irion_security" / "extension_security.test"


class IrionRuntimeTest(unittest.TestCase):
    def test_irion_is_a_self_sourced_standard_matrix_battery(self) -> None:
        plan = resolve_config(load_config(CONFIG_PATH))
        irion = next(case for case in plan.matrix()["include"] if case["name"] == "irion")

        self.assertEqual(irion["runner"], "standard")
        self.assertEqual(irion["sourceType"], "self")
        self.assertNotIn("repository", irion)
        self.assertNotIn("pin", irion)
        self.assertNotIn("submodules", irion)
        self.assertEqual(
            irion["runtime"],
            {
                "duckdbVersion": "v2.0.0",
                "ciToolsVersion": "969bc76276acec1c0a3922ff500d2ec3a1a3b037",
                "operatingSystem": "linux",
                "architecture": "x86_64",
                "githubRunner": "ubuntu-24.04",
            },
        )
        self.assertEqual([profile["name"] for profile in irion["profiles"]], ["baseline"])
        self.assertEqual(irion["profiles"][0]["tests"], "test/sql/irion/*")
        self.assertEqual(
            irion["profiles"][0]["testConfig"],
            {"kind": "upstream", "path": "test/configs/irion.json"},
        )

        security = next(
            case
            for case in plan.matrix()["include"]
            if case["name"] == "irion_extension_security"
        )
        self.assertEqual(security["runner"], "standard")
        self.assertEqual(security["sourceType"], "self")
        self.assertEqual([profile["name"] for profile in security["profiles"]], ["security"])
        self.assertEqual(
            security["profiles"][0]["tests"],
            "test/sql/irion_security/extension_security.test",
        )
        self.assertEqual(
            security["profiles"][0]["testConfig"]["excludedExtensions"],
            ["mssql", "bigquery"],
        )
        self.assertEqual(irion["services"], [])
        self.assertEqual(irion["prerequisites"], [])
        self.assertNotIn("accepted-failure", irion["capabilities"])

    def test_extension_security_scenario_uses_local_repository_and_blocks_community(self) -> None:
        test = SECURITY_TEST.read_text(encoding="utf-8")
        self.assertIn("require-env IRION_APPROVED_EXTENSION_REPO", test)
        self.assertIn("require-env IRION_COMMUNITY_EXTENSION_PATH", test)
        self.assertIn(
            "SET custom_extension_repository = '{IRION_APPROVED_EXTENSION_REPO}';",
            test,
        )
        self.assertIn("SET allow_community_extensions = false;", test)
        self.assertIn("FORCE INSTALL mssql;", test)
        # SQLLogicTest requires a concrete expected error for statement error;
        # omitting ---- causes a parser failure on both runner platforms.
        self.assertRegex(
            test,
            r"(?s)statement error\s+FORCE INSTALL mssql;\s+----\s+<REGEX>:",
        )
        self.assertEqual(test.count("statement error"), 1)

        standard_runner = (REPOSITORY_ROOT / "scripts" / "run-standard-tests.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("prepare_approved_extension_repo", standard_runner)
        self.assertIn("validate_community_load_policy(", standard_runner)
        self.assertIn("community-allowed-probe-home", standard_runner)
        self.assertIn("community-denied-probe-home", standard_runner)
        self.assertIn('env["IRION_APPROVED_EXTENSION_REPO"]', standard_runner)
        self.assertIn('env["IRION_COMMUNITY_EXTENSION_PATH"]', standard_runner)

        windows_runner = WINDOWS_BATTERY_RUNNER.read_text(encoding="utf-8")
        self.assertIn("'irion_extension_security'", windows_runner)
        self.assertIn("$nativeStandardBatteries", windows_runner)

    def test_workflow_uses_workspace_for_self_source(self) -> None:
        linux = (WORKFLOW_PATH.parent / "qa-linux.yml").read_text(encoding="utf-8")
        windows = (WORKFLOW_PATH.parent / "qa-windows.yml").read_text(encoding="utf-8")
        for workflow in (linux, windows):
            self.assertIn("if: matrix.sourceType == 'remote'", workflow)
            self.assertIn("repository: ${{ matrix.repository }}", workflow)
            self.assertIn("${{ steps.test_source.outputs.root }}", workflow)
        self.assertIn("if [[ '${{ matrix.sourceType }}' == 'self' ]]", linux)
        self.assertIn('root="${GITHUB_WORKSPACE}"', linux)
        self.assertIn("if ('${{ matrix.sourceType }}' -eq 'self')", windows)
        self.assertIn('$root = $env:GITHUB_WORKSPACE', windows)
        self.assertIn("if: matrix.name != 'irion_extension_security'", windows)
        self.assertIn("Install native security QA dependencies", windows)
        self.assertIn(
            "python -m pip install --disable-pip-version-check -r requirements/qa.txt",
            windows,
        )

    def test_both_platforms_select_all_batteries_independently(self) -> None:
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform):
                workflow = (WORKFLOW_PATH.parent / f"qa-{platform}.yml").read_text(
                    encoding="utf-8"
                )
                self.assertIn("  pull_request:", workflow)
                self.assertIn("  workflow_dispatch:", workflow)
                self.assertIn('--batteries "${REQUESTED_BATTERIES}"', workflow)
                self.assertIn(f"--platforms {platform}", workflow)
                self.assertNotIn('batteries="iceberg"', workflow)

    def test_repository_init_script_is_combined_with_extension_loads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upstream = root / "upstream"
            runtime = root / "runtime"
            output = root / "profile.json"

            (upstream / "test" / "configs").mkdir(parents=True)
            (upstream / "test" / "scripts").mkdir(parents=True)
            runtime.mkdir(parents=True)

            (upstream / "test" / "configs" / "irion.json").write_text(
                json.dumps(
                    {
                        "description": "Irion test profile",
                        "statically_loaded_extensions": ["core_functions", "parquet"],
                        "init_script": "test/scripts/initialize.sql",
                        "on_init": "CREATE TABLE on_init_marker(value INTEGER);",
                    }
                ),
                encoding="utf-8",
            )
            (upstream / "test" / "scripts" / "initialize.sql").write_text(
                "CREATE TABLE repository_marker(value INTEGER);\n",
                encoding="utf-8",
            )
            (runtime / "init-profile-baseline.sql").write_text(
                "LOAD json;\n",
                encoding="utf-8",
            )
            (runtime / "profiles.json").write_text(
                json.dumps(
                    [
                        {
                            "name": "baseline",
                            "tests": "test/sql/irion/*",
                            "initScript": "init-profile-baseline.sql",
                            "testConfig": {
                                "kind": "upstream",
                                "path": "test/configs/irion.json",
                            },
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (runtime / "extensions.json").write_text(
                json.dumps([{"name": "json"}]), encoding="utf-8"
            )
            (runtime / "profile-skips.json").write_text("{}\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(PROFILE_PREPARER),
                    str(runtime / "profiles.json"),
                    "baseline",
                    str(upstream),
                    str(output),
                    str(runtime / "extensions.json"),
                    str(runtime / "profile-skips.json"),
                    str(runtime),
                ],
                cwd=REPOSITORY_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            generated = json.loads(output.read_text(encoding="utf-8"))
            combined_init = Path(generated["init_script"])
            self.assertTrue(combined_init.is_file())
            combined_sql = combined_init.read_text(encoding="utf-8")
            self.assertIn("LOAD json;", combined_sql)
            self.assertIn("CREATE TABLE repository_marker", combined_sql)
            self.assertIn("CREATE TABLE on_init_marker", combined_sql)
            self.assertNotIn("on_init", generated)


if __name__ == "__main__":
    unittest.main()
