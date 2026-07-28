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
EXPECTED_MATRIX_SHA256 = "b128bcfd79eaa89688fa49a90734daf721a635cb8fcaa29fbf80f6655022d0f7"
EXPECTED_PLAN_SHA256 = "08fd08a19fa21627380e486d7c9e7f6c6dcdbd4ba3d19d4d70316c6a8987b4a7"


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

    def test_current_configuration_preserves_profile_contract(self) -> None:
        plan = resolve_config(load_config(CONFIG_PATH))
        matrix = plan.matrix()["include"]
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
        self.assertEqual(
            [profile["name"] for profile in matrix[0]["profiles"]],
            ["sql", "autoload"],
        )
        self.assertEqual(
            matrix[0]["profiles"][1]["testConfig"]["excludedExtensions"],
            ["httpfs"],
        )
        self.assertEqual(
            [profile["name"] for profile in matrix[1]["profiles"]],
            ["autoload", "sqlite", "postgres"],
        )
        self.assertEqual(
            matrix[1]["profiles"][2]["runtimeSetup"],
            "ducklake-postgres-15",
        )
        self.assertEqual(matrix[2]["tests"], "test/sql/*")
        self.assertEqual(matrix[-1]["tests"], "test/sql/*")
        compact_matrix = json.dumps(plan.matrix(), separators=(",", ":"))
        self.assertEqual(
            hashlib.sha256(compact_matrix.encode("utf-8")).hexdigest(),
            EXPECTED_MATRIX_SHA256,
        )
        self.assertEqual(plan.sha256(), EXPECTED_PLAN_SHA256)

    def test_disabled_battery_does_not_change_default_extensions(self) -> None:
        config = self.load_modified(
            lambda data: data["testBatteries"]["delta"].update(isEnabled=False)
        )
        plan = resolve_config(config)
        self.assertNotIn("delta", [case.name for case in plan.cases])
        httpfs = next(case for case in plan.cases if case.name == "httpfs")
        self.assertIn("delta", [extension.name for extension in httpfs.extensions])

    def test_disabled_default_does_not_disable_target_battery(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            next(
                item for item in data["defaultExtensions"] if item["name"] == "delta"
            )["isUsed"] = False

        plan = resolve_config(self.load_modified(mutate))
        delta = next(case for case in plan.cases if case.name == "delta")
        self.assertIn("delta", [extension.name for extension in delta.extensions])
        httpfs = next(case for case in plan.cases if case.name == "httpfs")
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

    def test_duplicate_profile_is_rejected(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["testBatteries"]["httpfs"]["profiles"].append(
                copy.deepcopy(data["testBatteries"]["httpfs"]["profiles"][0])
            )

        self.assert_config_error(mutate, "duplicate profile sql")

    def test_ignored_test_cannot_reference_unknown_profile(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["testBatteries"]["ducklake"]["ignoredTests"][0]["profiles"] = [
                "missing"
            ]

        self.assert_config_error(mutate, "references unknown profile missing")

    def test_standard_profile_requires_test_config(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            del data["testBatteries"]["delta"]["profiles"][0]["testConfig"]

        self.assert_config_error(mutate, "testConfig is required for the standard runner")

    def test_specialized_runner_rejects_runtime_setup(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["testBatteries"]["mssql"]["profiles"][0]["runtimeSetup"] = (
                "ducklake-postgres-15"
            )

        self.assert_config_error(mutate, "only supported by the standard runner")

    def test_profile_cannot_exclude_unresolved_extension(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["testBatteries"]["delta"]["profiles"][0]["testConfig"][
                "excludedExtensions"
            ] = ["missing_extension"]

        with self.assertRaisesRegex(ConfigError, "excludes unresolved extension"):
            resolve_config(self.load_modified(mutate))

    def test_schema_v1_is_rejected_after_profile_migration(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["schemaVersion"] = 1

        self.assert_config_error(mutate, "schemaVersion must be 2")


if __name__ == "__main__":
    unittest.main()
