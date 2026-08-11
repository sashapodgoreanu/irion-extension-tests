from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
AZURE_LOCAL_TESTS = "test/sql/http.test,test/sql/azure.test,test/sql/fs_logs.test,test/sql/azure_glob.test,test/sql/azure_writes.test,test/sql/azure_secret.test,test/sql/azure_vfs_ops.test,test/sql/http_log_redaction.test,test/sql/azure_scope_and_full_path.test"
UNITY_LOCAL_TESTS = "test/sql/local_oss_unity_catalog/unity_catalog.test,test/sql/local_oss_unity_catalog/http_logs.test"


class Phase5FinalizationTest(unittest.TestCase):
    def test_azure_local_profiles_keep_expected_fixture_configuration(self) -> None:
        config = yaml.safe_load((ROOT / "config/extensions.yml").read_text(encoding="utf-8"))
        azure = config["testBatteries"]["azure"]
        self.assertEqual([p["name"] for p in azure["profiles"]], ["azurite", "proxy"])
        self.assertEqual(azure["profiles"][0]["tests"], AZURE_LOCAL_TESTS)
        self.assertEqual(azure["profiles"][1]["tests"], "test/sql/proxy/*")
        self.assertTrue(azure["profiles"][1]["services"][1]["auth"])

    def test_unity_catalog_uses_pinned_oss_service(self) -> None:
        config = yaml.safe_load((ROOT / "config/extensions.yml").read_text(encoding="utf-8"))
        unity = config["testBatteries"]["unity_catalog"]
        self.assertEqual(unity["pin"], "fd851475780ca064d9706a5025ea6e5d1d9d7e23")
        self.assertEqual(unity["profiles"][0]["tests"], UNITY_LOCAL_TESTS)
        self.assertEqual(unity["services"][0]["type"], "unity-catalog-oss")
        self.assertRegex(unity["services"][0]["version"], r"^[0-9a-f]{40}$")
        self.assertEqual(
            [item["path"] for item in unity["ignoredTests"]],
            [
                "test/sql/local_oss_unity_catalog/uc_catalog_write.test",
                "test/sql/local_oss_unity_catalog/checkpoint.test",
            ],
        )

        manager = (ROOT / "scripts/service-manager.sh").read_text(encoding="utf-8")
        self.assertIn("qa_service_start_unity_catalog_oss", manager)
        self.assertIn("export UC_TEST_SERVER_RUNNING=1", manager)
        self.assertIn("DUCKDB_AZURE_PERSISTENT_SECRET_AVAILABLE=1", manager)

    def test_iceberg_is_not_an_accepted_failure(self) -> None:
        config = yaml.safe_load((ROOT / "config/extensions.yml").read_text(encoding="utf-8"))
        iceberg = config["testBatteries"]["iceberg"]
        self.assertEqual(iceberg["prerequisites"], [])
        self.assertEqual(
            iceberg["profiles"][0]["testConfig"]["excludedExtensions"], ["iceberg"]
        )


if __name__ == "__main__":
    unittest.main()
