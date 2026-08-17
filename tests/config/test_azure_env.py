from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
            # Legacy repository variables may still exist. The shared runner must
            # ignore them so upstream ABFSS tests skip on both operating systems.
            "ABFSS_STORAGE_ACCOUNT": "irionctstorageaccount",
            "ABFSS_DATA_DIR": "irionctstorageaccount-duckdb-tests-data/fixtures",
            "ABFSS_TEMP_DIR": "irionctstorageaccount-duckdb-tests-write/runs",
            "GITHUB_RUN_ID": "12345",
            "GITHUB_RUN_ATTEMPT": "2",
            "RUNNER_OS": "Windows",
        }

    def test_resolve_environment_uses_blob_cloud_paths_and_disables_abfss(self) -> None:
        values = azure_env.resolve_environment(self.base_environment())

        self.assertEqual(values["AZURE_AUTH_ENV"], "1")
        self.assertEqual(values["AZURE_PROVIDER"], "cloud")
        self.assertEqual(values["AZURE_PROTOCOL"], "az")
        self.assertEqual(values["AZURE_STORAGE_ACCOUNT"], "irionctstorageaccount")
        self.assertEqual(values["AZ_STORAGE_ACCOUNT"], "irionctstorageaccount")
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
        self.assertEqual(values["DUCKDB_AZURE_PUBLIC_CONTAINER_AVAILABLE"], "1")
        self.assertEqual(values["PUBLIC_AZ_STORAGE_ACCOUNT"], "duckdbtesting")

        for name in (
            "ABFSS_STORAGE_ACCOUNT",
            "ABFSS_DATA_DIR",
            "ABFSS_TEMP_DIR",
        ):
            self.assertNotIn(name, values)

        forwarded = values["WSLENV"].split(":")
        self.assertIn("AZURE_CLIENT_SECRET", forwarded)
        self.assertIn("AZURE_CONFIG_DIR", forwarded)
        self.assertIn("AZ_STORAGE_ACCOUNT", forwarded)
        self.assertIn("AZ_DATA_DIR", forwarded)
        self.assertIn("AZ_TEMP_DIR", forwarded)
        self.assertIn("DUCKDB_AZURE_PUBLIC_CONTAINER_AVAILABLE", forwarded)
        self.assertIn("PUBLIC_AZ_STORAGE_ACCOUNT", forwarded)
        self.assertNotIn("ABFSS_STORAGE_ACCOUNT", forwarded)
        self.assertNotIn("ABFSS_DATA_DIR", forwarded)
        self.assertNotIn("ABFSS_TEMP_DIR", forwarded)

    def test_existing_wslenv_is_preserved(self) -> None:
        environment = self.base_environment()
        environment["WSLENV"] = "EXISTING/path"

        values = azure_env.resolve_environment(environment)

        self.assertTrue(values["WSLENV"].startswith("EXISTING/path:"))
        self.assertIn("AZURE_TENANT_ID", values["WSLENV"].split(":"))

    def test_missing_required_blob_variable_fails_fast(self) -> None:
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

    def test_github_environment_contains_blob_and_public_values_only(self) -> None:
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
        self.assertIn("DUCKDB_AZURE_PUBLIC_CONTAINER_AVAILABLE=1\n", text)
        self.assertIn("PUBLIC_AZ_STORAGE_ACCOUNT=duckdbtesting\n", text)
        self.assertIn("WSLENV=", text)
        self.assertNotIn("ABFSS_STORAGE_ACCOUNT=", text)
        self.assertNotIn("ABFSS_DATA_DIR=", text)
        self.assertNotIn("ABFSS_TEMP_DIR=", text)

    def test_linux_github_runner_configures_expected_ca_compatibility_path(self) -> None:
        environment = {
            "RUNNER_OS": "Linux",
            "GITHUB_ACTIONS": "true",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "ca-certificates.crt"
            target = root / "pki" / "tls" / "certs" / "ca-bundle.crt"
            source.write_text("test-ca", encoding="utf-8")

            completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
            with (
                patch.object(azure_env.os, "geteuid", return_value=1000, create=True),
                patch.object(azure_env.shutil, "which", return_value="/usr/bin/sudo"),
                patch.object(azure_env.subprocess, "run", return_value=completed) as run,
            ):
                changed = azure_env.configure_linux_ca_bundle(
                    environment,
                    source=source,
                    target=target,
                )

        self.assertTrue(changed)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            run.call_args_list[0].args[0],
            ["/usr/bin/sudo", "mkdir", "-p", str(target.parent)],
        )
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["/usr/bin/sudo", "ln", "-sfn", str(source), str(target)],
        )

    def test_windows_runner_does_not_touch_linux_ca_path(self) -> None:
        with patch.object(azure_env.subprocess, "run") as run:
            changed = azure_env.configure_linux_ca_bundle(
                {"RUNNER_OS": "Windows", "GITHUB_ACTIONS": "true"}
            )
        self.assertFalse(changed)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
