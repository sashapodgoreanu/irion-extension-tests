from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from qa import ConfigError, load_config, resolve_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPOSITORY_ROOT / "config" / "extensions.yml"
EXPECTED_MATRIX_SHA256 = "779d96d9e0be7081b546112e93654e52b776262ee12803856071ce681ffbe485"


class ConfigTestCase(unittest.TestCase):
    def load_source(self) -> dict[str, Any]:
        data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)
        return data

    def load_modified(self, mutate) -> Any:
        data = copy.deepcopy(self.load_source())
        mutate(data)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "extensions.yml"
            path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            return load_config(path)

    def assert_config_error(self, mutate, expected: str) -> None:
        with self.assertRaisesRegex(ConfigError, expected):
            self.load_modified(mutate)

    def test_current_configuration_preserves_matrix_contract(self) -> None:
        resolved = resolve_config(load_config(CONFIG_PATH))
        matrix = resolved.matrix()["include"]
        self.assertEqual(
            [item["name"] for item in matrix],
            [
                "httpfs",
                "ducklake",
                "postgres_scanner",
                "delta",
                "iceberg",
                "azure",
                "unity_catalog",
                "mssql",
            ],
        )
        self.assertTrue(all(item["duckdbVersion"] == "v1.5.4" for item in matrix))
        self.assertEqual(matrix[0]["submodules"], "recursive")
        self.assertEqual(matrix[-1]["submodules"], "false")
        self.assertEqual(
            [extension["name"] for extension in matrix[0]["extensions"][:9]],
            [
                "httpfs",
                "mssql",
                "ducklake",
                "postgres_scanner",
                "icu",
                "azure",
                "delta",
                "iceberg",
                "unity_catalog",
            ],
        )
        self.assertEqual(
            next(
                extension
                for extension in matrix[-1]["extensions"]
                if extension["name"] == "mssql"
            ),
            {"name": "mssql", "installFrom": "community"},
        )
        compact_matrix = resolved.github_outputs()[0].removeprefix("matrix=")
        self.assertEqual(json.loads(compact_matrix), resolved.matrix())
        self.assertEqual(
            hashlib.sha256(compact_matrix.encode("utf-8")).hexdigest(),
            EXPECTED_MATRIX_SHA256,
        )

    def test_disabled_battery_does_not_change_default_extensions(self) -> None:
        config = self.load_modified(
            lambda data: data["testBatteries"]["delta"].update(isEnabled=False)
        )
        resolved = resolve_config(config)
        self.assertNotIn("delta", [battery.name for battery in resolved.batteries])
        httpfs = next(battery for battery in resolved.batteries if battery.name == "httpfs")
        self.assertIn("delta", [extension.name for extension in httpfs.extensions])

    def test_disabled_default_does_not_disable_target_battery(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            next(
                item for item in data["defaultExtensions"] if item["name"] == "delta"
            )["isUsed"] = False

        resolved = resolve_config(self.load_modified(mutate))
        delta = next(battery for battery in resolved.batteries if battery.name == "delta")
        self.assertIn("delta", [extension.name for extension in delta.extensions])
        httpfs = next(battery for battery in resolved.batteries if battery.name == "httpfs")
        self.assertNotIn("delta", [extension.name for extension in httpfs.extensions])

    def test_conflicting_install_origin_is_rejected(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            next(
                item
                for item in data["testBatteries"]["mssql"]["extensions"]
                if item["name"] == "mssql"
            )["installFrom"] = "core"

        with self.assertRaisesRegex(ConfigError, "conflicts with the resolved installFrom"):
            resolve_config(self.load_modified(mutate))

    def test_unknown_battery_property_is_rejected(self) -> None:
        self.assert_config_error(
            lambda data: data["testBatteries"]["httpfs"].update(ignoredTest=[]),
            "Additional properties are not allowed",
        )

    def test_unknown_extension_property_is_rejected(self) -> None:
        self.assert_config_error(
            lambda data: data["defaultExtensions"][0].update(source="core"),
            "Additional properties are not allowed",
        )

    def test_disabled_battery_is_still_validated(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["testBatteries"]["delta"]["isEnabled"] = False
            data["testBatteries"]["delta"]["runner"] = "unknown"

        self.assert_config_error(mutate, "is not one of")

    def test_duplicate_extension_is_rejected(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["defaultExtensions"].append(copy.deepcopy(data["defaultExtensions"][0]))

        self.assert_config_error(mutate, "duplicate extension httpfs")

    def test_ignored_path_cannot_escape_checkout(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["testBatteries"]["httpfs"]["ignoredTests"][0]["path"] = (
                "../outside.test"
            )

        self.assert_config_error(mutate, "must stay inside the upstream checkout")

    def test_at_least_one_battery_must_be_enabled(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            for battery in data["testBatteries"].values():
                battery["isEnabled"] = False

        with self.assertRaisesRegex(ConfigError, "at least one test battery"):
            resolve_config(self.load_modified(mutate))


if __name__ == "__main__":
    unittest.main()
