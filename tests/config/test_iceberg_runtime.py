from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from qa import load_config, resolve_config

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config/extensions.yml"


class IcebergDisabledContractTests(unittest.TestCase):
    def test_iceberg_and_its_dependencies_are_disabled_indefinitely(self) -> None:
        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        iceberg = config["testBatteries"]["iceberg"]
        self.assertFalse(iceberg["isEnabled"])
        self.assertEqual(iceberg["services"], [])
        self.assertEqual(iceberg["prerequisites"], [])
        self.assertEqual(iceberg["extensions"], [])
        self.assertEqual(iceberg["profiles"][0]["services"], [])
        self.assertEqual(
            iceberg["profiles"][0]["testConfig"]["excludedExtensions"], []
        )
        self.assertFalse(next(
            entry["isUsed"] for entry in config["defaultExtensions"]
            if entry["name"] == "iceberg"
        ))
        self.assertFalse(any(
            entry["name"] == "avro" and entry["isUsed"]
            for entry in config["defaultExtensions"]
        ))

    def test_no_active_test_battery_installs_iceberg_or_avro(self) -> None:
        plan = resolve_config(load_config(CONFIG_PATH))
        self.assertNotIn("iceberg", {case.name for case in plan.cases})
        for case in plan.cases:
            installed = {extension.name for extension in case.extensions}
            self.assertNotIn("iceberg", installed, case.name)
            self.assertNotIn("avro", installed, case.name)


if __name__ == "__main__":
    unittest.main()
