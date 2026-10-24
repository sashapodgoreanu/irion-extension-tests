"""Validate that test source pins match the observed DuckDB binary versions."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class ExtensionBinaryPinsTest(unittest.TestCase):
    def test_pins_align_with_distributed_binary_versions(self) -> None:
        config = yaml.safe_load(
            (ROOT / "config/extensions.yml").read_text(encoding="utf-8")
        )
        lock = yaml.safe_load(
            (ROOT / "config/extension-binary-pins.yml").read_text(encoding="utf-8")
        )
        self.assertEqual(lock["duckdbVersion"], config["duckdb"]["version"])
        batteries = config["testBatteries"]
        enabled_remote = {
            name for name, value in batteries.items()
            if value["isEnabled"] and value.get("source") == "remote"
        }
        self.assertEqual(enabled_remote, set(lock["batteries"]))
        for name, binary in lock["batteries"].items():
            with self.subTest(extension=name):
                battery = batteries[name]
                self.assertTrue(battery["isEnabled"])
                self.assertEqual(battery["repository"], binary["repository"])
                pin = battery["pin"]
                version = binary["binaryVersion"].lower().removeprefix("v")
                if re.fullmatch(r"[0-9a-f]{7,40}", version):
                    self.assertRegex(pin, r"^[0-9a-f]{40}$")
                    self.assertTrue(
                        pin.startswith(version),
                        f"{name}: source {pin} does not match binary {version}",
                    )
                    self.assertNotIn("releaseCommit", binary)
                else:
                    self.assertRegex(version, r"^\d+\.\d+\.\d+$")
                    self.assertEqual(binary["sourceTag"].lower().removeprefix("v"), version)
                    self.assertRegex(binary["releaseCommit"], r"^[0-9a-f]{40}$")
                    self.assertIn(
                        pin, (binary["sourceTag"], binary["releaseCommit"]),
                        f"{name}: source pin must be the signed release tag or its exact commit",
                    )

    def test_runners_keep_fail_closed_alignment_checks(self) -> None:
        pg = (ROOT / "scripts/run-postgres-scanner-tests.sh").read_text(encoding="utf-8")
        mssql = (ROOT / "scripts/run-mssql-tests-base.sh").read_text(encoding="utf-8")
        self.assertIn("source/binary commit mismatch", pg)
        self.assertIn("expected_commit.startswith(reported_commit)", pg)
        self.assertIn("MSSQL source/binary version mismatch", mssql)
        self.assertIn("matches_release = reported_version == expected_release_version", mssql)
        self.assertIn("matches_commit = (", mssql)
        self.assertIn("if not (matches_release or matches_commit):", mssql)

    def test_iceberg_stays_disabled(self) -> None:
        config = yaml.safe_load(
            (ROOT / "config/extensions.yml").read_text(encoding="utf-8")
        )
        self.assertFalse(config["testBatteries"]["iceberg"]["isEnabled"])
        self.assertEqual(config["testBatteries"]["iceberg"]["extensions"], [])
        self.assertNotIn("iceberg", yaml.safe_load(
            (ROOT / "config/extension-binary-pins.yml").read_text(encoding="utf-8")
        )["batteries"])


if __name__ == "__main__":
    unittest.main()
