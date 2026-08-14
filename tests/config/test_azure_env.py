from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY_ROOT / "scripts" / "init-azure-test-env.py"

spec = importlib.util.spec_from_file_location("init_azure_test_env", MODULE_PATH)
assert spec is not None and spec.loader is not None
azure_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(azure_env)


class AzureEnvironmentTestCase(unittest.TestCase):
    def base_environment(self) -> dict[str, str]:
        return {
            "AZURE_TENANT_ID": "tenant",
            "AZURE_CLIENT_ID": "client",
            "AZURE_CLIENT_SECRET": "secret",
            "AZ_STORAGE_ACCOUNT": "irionctstorageaccount",
            "AZ_DATA_DIR": "irionctstorageaccount-duckdb-tests-data/fixtures",
            "AZ_TEMP_DIR": "irionctstorageaccount-duckdb-tests-write/runs",
            "GITHUB_RUN_ID": "12345",
            "GITHUB_RUN_ATTEMPT": "2",
            "RUNNER_OS": "Windows",
        }

    def test_resolve_environment_uses_configured_cloud_paths(self) -> None:
        values = azure_env.resolve_environment(self.base_environment())

        self.assertEqual(values["AZURE_AUTH_ENV"], "1")
        self.assertEqual(values["AZURE_PROVIDER"], "cloud")
        self.assertEqual(values["AZURE_PROTOCOL"], "az")
        self.assertEqual(values["AZURE_STORAGE_ACCOUNT"], "irionctstorageaccount")
        self.assertEqual(
            values["AZ_DATA_DIR"],
            "irionctstorageaccount-duckdb-tests-data/fixtures",
        )
        self.assertEqual(
            values["AZ_TEMP_DIR"],
            "irionctstorageaccount-duckdb-tests-write/runs/12345-2-Windows",
        )
        self.assertEqual(values["DATA_DIR"], values["AZ_DATA_DIR"])
        self.assertEqual(values["TEMP_DIR"], values["AZ_TEMP_DIR"])
        forwarded = values["WSLENV"].split(":")
        self.assertIn("AZURE_CLIENT_SECRET", forwarded)
        self.assertIn("AZ_STORAGE_ACCOUNT", forwarded)
        self.assertIn("AZ_DATA_DIR", forwarded)
        self.assertIn("AZ_TEMP_DIR", forwarded)

    def test_existing_wslenv_is_preserved(self) -> None:
        environment = self.base_environment()
        environment["WSLENV"] = "EXISTING/path"

        values = azure_env.resolve_environment(environment)

        self.assertTrue(values["WSLENV"].startswith("EXISTING/path:"))
        self.assertIn("AZURE_TENANT_ID", values["WSLENV"].split(":"))

    def test_missing_actions_variable_fails_fast(self) -> None:
        environment = self.base_environment()
        del environment["AZ_DATA_DIR"]

        with self.assertRaisesRegex(
            azure_env.AzureEnvironmentError,
            "AZ_DATA_DIR",
        ):
            azure_env.resolve_environment(environment)

    def test_storage_roots_reject_full_uris(self) -> None:
        environment = self.base_environment()
        environment["AZ_TEMP_DIR"] = "az://container/runs"

        with self.assertRaisesRegex(
            azure_env.AzureEnvironmentError,
            "container/path",
        ):
            azure_env.resolve_environment(environment)

    def test_github_environment_contains_configured_and_derived_values(self) -> None:
        values = azure_env.resolve_environment(self.base_environment())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "github-env"
            azure_env.append_github_environment(path, values)
            text = path.read_text(encoding="utf-8")

        self.assertIn("AZURE_TENANT_ID=tenant\n", text)
        self.assertIn("AZURE_CLIENT_ID=client\n", text)
        self.assertIn("AZURE_CLIENT_SECRET=secret\n", text)
        self.assertIn("AZ_STORAGE_ACCOUNT=irionctstorageaccount\n", text)
        self.assertIn(
            "AZ_DATA_DIR=irionctstorageaccount-duckdb-tests-data/fixtures\n",
            text,
        )
        self.assertIn(
            "AZ_TEMP_DIR=irionctstorageaccount-duckdb-tests-write/runs/12345-2-Windows\n",
            text,
        )
        self.assertIn("AZURE_PROVIDER=cloud\n", text)
        self.assertIn("WSLENV=", text)


if __name__ == "__main__":
    unittest.main()
