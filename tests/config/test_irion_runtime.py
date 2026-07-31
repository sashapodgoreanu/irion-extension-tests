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


class IrionRuntimeTest(unittest.TestCase):
    def test_irion_is_a_standard_matrix_battery(self) -> None:
        plan = resolve_config(load_config(CONFIG_PATH))
        irion = next(case for case in plan.matrix()["include"] if case["name"] == "irion")

        self.assertEqual(irion["runner"], "standard")
        self.assertEqual(irion["repository"], "sashapodgoreanu/irion-extension-tests")
        self.assertEqual(irion["pin"], "003-irion-test-battery")
        self.assertEqual([profile["name"] for profile in irion["profiles"]], ["baseline"])
        self.assertEqual(irion["profiles"][0]["tests"], "test/sql/irion/*")
        self.assertEqual(
            irion["profiles"][0]["testConfig"],
            {"kind": "upstream", "path": "test/configs/irion.json"},
        )
        self.assertEqual(irion["services"], [])
        self.assertEqual(irion["prerequisites"], [])
        self.assertNotIn("accepted-failure", irion["capabilities"])

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
