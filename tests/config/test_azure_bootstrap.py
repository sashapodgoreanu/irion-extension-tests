from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY_ROOT / "scripts" / "bootstrap-azure-test-data.py"

spec = importlib.util.spec_from_file_location("bootstrap_azure_test_data", MODULE_PATH)
assert spec is not None and spec.loader is not None
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class AzureBootstrapTestCase(unittest.TestCase):
    def base_environment(self) -> dict[str, str]:
        return {
            "AZURE_TENANT_ID": "tenant",
            "AZURE_CLIENT_ID": "client",
            "AZURE_CLIENT_SECRET": "secret",
            "AZ_STORAGE_ACCOUNT": "irionctstorageaccount",
            "AZ_DATA_DIR": "irionctstorageaccount-duckdb-tests-data/fixtures",
            "AZ_TEMP_DIR": "irionctstorageaccount-duckdb-tests-write/runs/123-Windows",
            "ABFSS_STORAGE_ACCOUNT": "irionctstorageaccount",
            "ABFSS_DATA_DIR": "irionctstorageaccount-duckdb-tests-data/fixtures",
            "ABFSS_TEMP_DIR": "irionctstorageaccount-duckdb-tests-write/runs/123-Windows",
            "AZURE_CONFIG_DIR": r"C:\Users\runneradmin\.azure",
        }

    def test_blob_and_abfss_fixture_targets_are_deduplicated(self) -> None:
        inputs = bootstrap.required_environment(self.base_environment())
        self.assertEqual(
            bootstrap.storage_targets(inputs),
            [
                (
                    "irionctstorageaccount",
                    "irionctstorageaccount-duckdb-tests-data",
                    "fixtures",
                ),
                (
                    "irionctstorageaccount",
                    "duckdblabs-data",
                    "common/azure_data",
                ),
            ],
        )
        self.assertEqual(
            bootstrap.writable_containers(inputs),
            {
                ("irionctstorageaccount", "irionctstorageaccount-duckdb-tests-data"),
                ("irionctstorageaccount", "irionctstorageaccount-duckdb-tests-write"),
                ("irionctstorageaccount", "duckdblabs-data"),
                ("irionctstorageaccount", "duckdblabs-write-testing"),
            },
        )

    def test_missing_abfss_variable_fails_fast(self) -> None:
        environment = self.base_environment()
        del environment["ABFSS_STORAGE_ACCOUNT"]
        with self.assertRaisesRegex(bootstrap.AzureBootstrapError, "ABFSS_STORAGE_ACCOUNT"):
            bootstrap.required_environment(environment)

    def test_runtime_auth_environment_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "github-env"
            bootstrap.append_runtime_auth_environment(
                path, "token-value", r"C:\Users\runneradmin\.azure"
            )
            text = path.read_text(encoding="utf-8")
        self.assertEqual(
            text,
            "AZ_CLI_LOGGED_IN=1\n"
            "AZURE_ACCESS_TOKEN=token-value\n"
            "AZURE_CONFIG_DIR=C:\\Users\\runneradmin\\.azure\n",
        )

    def test_bootstrap_uploads_configured_and_upstream_fixture_namespaces(self) -> None:
        environment = self.base_environment()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "data"
            fixture.mkdir()
            (fixture / "l.parquet").write_bytes(b"parquet")
            (fixture / "README.md").write_text("fixture", encoding="utf-8")
            github_env = root / "github-env"
            environment["GITHUB_ENV"] = str(github_env)

            uploaded: list[tuple[str, str, str]] = []
            ensured: list[tuple[str, str]] = []

            with (
                patch.object(bootstrap, "login") as login,
                patch.object(
                    bootstrap,
                    "ensure_container",
                    side_effect=lambda account, container: ensured.append((account, container)),
                ),
                patch.object(
                    bootstrap,
                    "upload_fixture",
                    side_effect=lambda account, container, prefix, _root, file_path: uploaded.append(
                        (account, container, bootstrap.blob_name(prefix, file_path.relative_to(fixture)))
                    ),
                ),
                patch.object(bootstrap, "storage_access_token", return_value="token-value"),
            ):
                count = bootstrap.bootstrap(root, environment)

            login.assert_called_once()
            self.assertEqual(count, 2)
            self.assertEqual(len(ensured), 4)
            self.assertEqual(len(uploaded), 4)
            self.assertIn(
                (
                    "irionctstorageaccount",
                    "irionctstorageaccount-duckdb-tests-data",
                    "fixtures/l.parquet",
                ),
                uploaded,
            )
            self.assertIn(
                (
                    "irionctstorageaccount",
                    "duckdblabs-data",
                    "common/azure_data/l.parquet",
                ),
                uploaded,
            )
            runtime_environment = github_env.read_text(encoding="utf-8")
            self.assertIn("AZ_CLI_LOGGED_IN=1", runtime_environment)
            self.assertIn(
                "AZURE_CONFIG_DIR=C:\\Users\\runneradmin\\.azure",
                runtime_environment,
            )


if __name__ == "__main__":
    unittest.main()
