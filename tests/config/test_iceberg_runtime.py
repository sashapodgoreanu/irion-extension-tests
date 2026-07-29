from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from qa import load_config, resolve_config

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "extensions.yml"
PREPARE_BATTERY = ROOT / "scripts" / "prepare-test-battery.py"
PREPARE_PROFILE = ROOT / "scripts" / "prepare-standard-profile.py"
ICEBERG_COMMIT = "757264559e745be697e9306e144e8889eb1dc024"


class IcebergRuntimeTest(unittest.TestCase):
    def test_iceberg_profile_matches_binary_and_disables_repository_autoload(self) -> None:
        plan = resolve_config(load_config(CONFIG_PATH))
        matrix_case = next(
            item for item in plan.matrix()["include"] if item["name"] == "iceberg"
        )
        self.assertEqual(matrix_case["pin"], ICEBERG_COMMIT)
        self.assertEqual(matrix_case["prerequisites"], [])
        self.assertEqual(matrix_case["capabilities"], [])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "iceberg.json"
            runtime = root / "runtime"
            upstream = root / "upstream"
            profile = root / "profile.json"
            source.write_text(json.dumps(matrix_case), encoding="utf-8")
            upstream.mkdir()

            subprocess.run(
                [sys.executable, str(PREPARE_BATTERY), str(source), str(runtime)],
                check=True,
                cwd=ROOT,
            )
            subprocess.run(
                [
                    sys.executable,
                    str(PREPARE_PROFILE),
                    str(runtime / "profiles.json"),
                    "all",
                    str(upstream),
                    str(profile),
                    str(runtime / "extensions.json"),
                    str(runtime / "profile-skips.json"),
                    str(runtime),
                ],
                check=True,
                cwd=ROOT,
            )

            generated = json.loads(profile.read_text(encoding="utf-8"))
            self.assertEqual(generated["autoloading"], "none")
            self.assertNotIn("LOAD iceberg;", generated["on_new_connection"])
            self.assertEqual(
                generated["statically_loaded_extensions"],
                ["core_functions", "parquet", "avro", "httpfs"],
            )
            self.assertEqual(
                generated["settings"],
                [
                    {"name": "autoload_known_extensions", "value": "false"},
                    {"name": "autoinstall_known_extensions", "value": "false"},
                ],
            )


if __name__ == "__main__":
    unittest.main()
