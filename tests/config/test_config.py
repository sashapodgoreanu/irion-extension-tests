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
EXPECTED_MATRIX_SHA256 = "920042dded27b301e00d9572793592f173a02a5590e62d5aa40a4e930f014603"
EXPECTED_PLAN_SHA256 = "4c5051abf02dec41561edb3e495190b04a6356fdbfb41da01746a3000246191c"


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

    def test_current_configuration_preserves_batteries_and_compiles_services(self) -> None:
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
                "bigquery",
                "mssql",
            ],
        )
        self.assertTrue(all(item["duckdbVersion"] == "v1.5.4" for item in matrix))
        self.assertTrue(all("setup" not in item for item in matrix))

        httpfs = matrix[0]
        self.assertEqual(
            [(item["name"], item["type"]) for item in httpfs["services"]],
            [
                ("http-server", "python-http"),
                ("proxy", "squid"),
                ("object-store", "httpfs-minio"),
            ],
        )
        self.assertEqual(httpfs["capabilities"], ["squid", "docker-compose"])
        self.assertEqual([profile["name"] for profile in httpfs["profiles"]], ["sql"])
        self.assertNotIn(
            "test/extension/*", [profile["tests"] for profile in httpfs["profiles"]]
        )

        ducklake = matrix[1]
        postgres_profile = next(
            profile for profile in ducklake["profiles"] if profile["name"] == "postgres"
        )
        self.assertEqual(
            postgres_profile["services"],
            [
                {
                    "name": "postgres-catalog",
                    "type": "postgres",
                    "database": "ducklakedb",
                    "port": 5432,
                    "username": "postgres",
                    "version": "15",
                }
            ],
        )
        self.assertEqual(ducklake["capabilities"], ["docker", "postgres-client"])

        postgres = matrix[2]
        self.assertEqual(postgres["services"][0]["type"], "postgres")
        self.assertEqual(postgres["services"][0]["version"], "17")
        self.assertEqual(postgres["capabilities"], ["docker", "postgres-client"])

        azure = next(case for case in matrix if case["name"] == "azure")
        self.assertEqual(
            azure["services"],
            [{"name": "storage-emulator", "type": "azurite", "port": 10000}],
        )
        self.assertEqual(azure["capabilities"], ["azurite", "squid"])
        self.assertEqual(azure["prerequisites"], [])
        self.assertEqual([profile["name"] for profile in azure["profiles"]], ["azurite", "proxy"])
        self.assertEqual(azure["profiles"][0]["tests"], "test/sql/*.test")
        self.assertEqual(azure["profiles"][1]["tests"], "test/sql/proxy/*")
        self.assertEqual(azure["profiles"][1]["services"][1]["auth"], True)

        unity = next(case for case in matrix if case["name"] == "unity_catalog")
        self.assertEqual(unity["pin"], "dbca44d4dcc67c196af5fd910f0f26ce56d4930e")
        self.assertEqual(unity["services"][0]["type"], "unity-catalog-oss")
        self.assertEqual(unity["capabilities"], ["unity-catalog-oss"])
        self.assertEqual([profile["name"] for profile in unity["profiles"]], ["oss"])

        bigquery = next(case for case in matrix if case["name"] == "bigquery")
        self.assertEqual(bigquery["services"], [])
        self.assertEqual(
            bigquery["prerequisites"],
            [
                {"type": "google-bigquery"},
                {"type": "external-cloud-account"},
            ],
        )
        self.assertEqual(
            bigquery["capabilities"], ["google-cloud-auth", "accepted-failure"]
        )

        iceberg = next(case for case in matrix if case["name"] == "iceberg")
        self.assertEqual(
            iceberg["prerequisites"], [{"type": "external-cloud-account"}]
        )
        self.assertEqual(iceberg["capabilities"], ["accepted-failure"])
        self.assertEqual(
            [
                case["name"]
                for case in matrix
                if "accepted-failure" in case["capabilities"]
            ],
            ["iceberg", "bigquery"],
        )

        mssql = next(case for case in matrix if case["name"] == "mssql")
        self.assertEqual(mssql["services"][0]["type"], "sqlserver")
        self.assertEqual(mssql["capabilities"], ["docker-compose"])

        for case in matrix:
            extension = next(
                item for item in case["extensions"] if item["name"] == "bigquery"
            )
            self.assertEqual(extension["installFrom"], "community")

        compact_matrix = json.dumps(plan.matrix(), separators=(",", ":"))
        matrix_hash = hashlib.sha256(compact_matrix.encode("utf-8")).hexdigest()
        self.assertEqual(matrix_hash, EXPECTED_MATRIX_SHA256, matrix_hash)
        plan_hash = plan.sha256()
        self.assertEqual(plan_hash, EXPECTED_PLAN_SHA256, plan_hash)

    def test_disabled_battery_does_not_change_default_extensions(self) -> None:
        config = self.load_modified(
            lambda data: data["testBatteries"]["delta"].update(isEnabled=False)
        )
        plan = resolve_config(config)
        self.assertNotIn("delta", [case.name for case in plan.cases])
        httpfs = next(case for case in plan.cases if case.name == "httpfs")
        self.assertIn("delta", [extension.name for extension in httpfs.extensions])

    def test_conflicting_install_origin_is_rejected(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            next(
                item
                for item in data["testBatteries"]["mssql"]["extensions"]
                if item["name"] == "mssql"
            )["installFrom"] = "core"

        with self.assertRaisesRegex(ConfigError, "conflicts with the resolved installFrom"):
            resolve_config(self.load_modified(mutate))

    def test_legacy_setup_property_is_rejected(self) -> None:
        self.assert_config_error(
            lambda data: data["testBatteries"]["httpfs"].update(
                setup="httpfs-services"
            ),
            "Additional properties are not allowed",
        )

    def test_legacy_runtime_setup_property_is_rejected(self) -> None:
        self.assert_config_error(
            lambda data: data["testBatteries"]["ducklake"]["profiles"][2].update(
                runtimeSetup="ducklake-postgres-15"
            ),
            "Additional properties are not allowed",
        )

    def test_duplicate_battery_service_is_rejected(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["testBatteries"]["httpfs"]["services"].append(
                copy.deepcopy(data["testBatteries"]["httpfs"]["services"][0])
            )

        self.assert_config_error(mutate, "duplicate service http-server")

    def test_duplicate_prerequisite_is_rejected(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["testBatteries"]["bigquery"]["prerequisites"].append(
                {"type": "google-bigquery"}
            )

        self.assert_config_error(mutate, "duplicate prerequisite google-bigquery")

    def test_profile_service_cannot_shadow_battery_service(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["testBatteries"]["httpfs"]["profiles"][0]["services"] = [
                {"name": "proxy", "type": "squid", "port": 4128}
            ]

        self.assert_config_error(mutate, "duplicates battery service proxy")

    def test_specialized_runner_rejects_profile_services(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["testBatteries"]["mssql"]["profiles"][0]["services"] = [
                {
                    "name": "extra-postgres",
                    "type": "postgres",
                    "version": "15",
                    "database": "testdb",
                    "port": 5543,
                }
            ]

        self.assert_config_error(mutate, "only supported by the standard runner")

    def test_service_contract_is_strict(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["testBatteries"]["httpfs"]["services"][0]["unknown"] = True

        self.assert_config_error(mutate, "is not valid under any of the given schemas")

    def test_schema_v3_is_rejected_after_azurite_migration(self) -> None:
        self.assert_config_error(
            lambda data: data.update(schemaVersion=3), "schemaVersion must be 4"
        )

    def test_profile_cannot_exclude_unresolved_extension(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["testBatteries"]["delta"]["profiles"][0]["testConfig"][
                "excludedExtensions"
            ] = ["missing_extension"]

        with self.assertRaisesRegex(ConfigError, "excludes unresolved extension"):
            resolve_config(self.load_modified(mutate))

    def test_at_least_one_battery_must_be_enabled(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            for battery in data["testBatteries"].values():
                battery["isEnabled"] = False

        with self.assertRaisesRegex(ConfigError, "at least one test battery"):
            resolve_config(self.load_modified(mutate))


if __name__ == "__main__":
    unittest.main()
