from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
AZURE_LOCAL_TESTS = "test/sql/http.test,test/sql/azure.test,test/sql/fs_logs.test,test/sql/azure_glob.test,test/sql/azure_writes.test,test/sql/azure_secret.test,test/sql/azure_vfs_ops.test,test/sql/http_log_redaction.test,test/sql/azure_scope_and_full_path.test"
UNITY_LOCAL_TESTS = "test"


class Phase5FinalizationTest(unittest.TestCase):
    def test_azure_local_profiles_keep_expected_fixture_configuration(self) -> None:
        config = yaml.safe_load((ROOT / "config/extensions.yml").read_text(encoding="utf-8"))
        azure = config["testBatteries"]["azure"]
        self.assertEqual([p["name"] for p in azure["profiles"]], ["azurite", "proxy"])
        self.assertEqual(azure["profiles"][0]["tests"], AZURE_LOCAL_TESTS)
        self.assertEqual(azure["profiles"][1]["tests"], "test/sql/proxy/*")
        self.assertTrue(azure["profiles"][1]["services"][1]["auth"])

    def test_unity_catalog_uses_pinned_pytest_suite(self) -> None:
        config = yaml.safe_load((ROOT / "config/extensions.yml").read_text(encoding="utf-8"))
        unity = config["testBatteries"]["unity_catalog"]
        self.assertEqual(unity["runner"], "unity-catalog-pytest")
        self.assertEqual(unity["pin"], "cc59382f5292997293a57c2ab336c9aa97c05f2d")
        self.assertEqual(unity["profiles"][0]["tests"], UNITY_LOCAL_TESTS)
        self.assertEqual(unity["services"], [])
        self.assertEqual(unity["profiles"][0]["services"], [])
        self.assertEqual(
            [test["path"] for test in unity["ignoredTests"]],
            [
                "test/oss_local/table-cmt/create_table.py",
                "test/oss_local/table-plain/create_table.py",
            ],
        )
        self.assertTrue(
            all("TABLE_NOT_FOUND" in test["reason"] for test in unity["ignoredTests"])
        )

        runner = (ROOT / "scripts/run-unity-catalog-pytest.sh").read_text(encoding="utf-8")
        self.assertIn('uv run pytest -p unity_catalog_http_error_plugin -n0 -s', runner)
        self.assertIn('BUILD_DIR="${UPSTREAM_ROOT}/build/release"', runner)
        self.assertIn('LD_LIBRARY_PATH="${PWD}/build/release/src"', runner)
        self.assertIn('BUILD_DIR=build/release', runner)
        self.assertIn('if [[ "${QA_NATIVE_WINDOWS:-0}" != "1" ]]; then', runner)
        self.assertIn('required+=("${ARTIFACT_DIR}/lib/libduckdb.so")', runner)
        self.assertIn('if [[ -f "${ARTIFACT_DIR}/lib/libduckdb.so" ]]; then', runner)
        self.assertIn('ghcr.io/benfleis/ducktest-unitycatalog:ci', runner)
        self.assertIn('"${BUILD_DIR}/extension/${extension_name}"', runner)

        windows_setup = (ROOT / "scripts/setup-windows-wsl-runtime.ps1").read_text(encoding="utf-8")
        self.assertIn("if ($BatteryName -eq 'unity_catalog')", windows_setup)
        self.assertIn("UV_INSTALL_DIR=/usr/local/bin", windows_setup)
        self.assertIn("uv --version", windows_setup)

        workflow = (ROOT / ".github/workflows/qa-linux.yml").read_text(encoding="utf-8")
        self.assertIn("uv pip install --python .venv/bin/python -r requirements/qa.txt", workflow)

    def test_iceberg_is_not_an_accepted_failure(self) -> None:
        config = yaml.safe_load((ROOT / "config/extensions.yml").read_text(encoding="utf-8"))
        iceberg = config["testBatteries"]["iceberg"]
        self.assertEqual(iceberg["prerequisites"], [])
        self.assertEqual(
            iceberg["profiles"][0]["testConfig"]["excludedExtensions"], []
        )
        self.assertFalse(iceberg["isEnabled"])
        self.assertEqual(iceberg["extensions"], [])


if __name__ == "__main__":
    unittest.main()
