from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_WSL_RUNTIME = REPOSITORY_ROOT / "scripts" / "windows-wsl-runtime.sh"


class WindowsWslRuntimeTestCase(unittest.TestCase):
    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    @unittest.skipUnless(shutil.which("rsync"), "rsync is required")
    def test_authenticated_azure_cli_profile_is_mirrored_to_isolated_userprofile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            azure_config = root / "azure-cli"
            home.mkdir()
            azure_config.mkdir()
            (azure_config / "azureProfile.json").write_text("profile", encoding="utf-8")
            (azure_config / "msal_token_cache.bin").write_bytes(b"token-cache")

            env = dict(os.environ)
            env.update(
                {
                    "HOME": str(home),
                    "AZ_CLI_LOGGED_IN": "1",
                    "AZURE_CONFIG_DIR": str(azure_config),
                    "QA_WSL_RUNTIME_PY": str(root / "unused.py"),
                }
            )
            script = f'''source "{WINDOWS_WSL_RUNTIME}"
qa_sync_azure_cli_profile_to_windows_home
'''

            result = subprocess.run(
                ["bash", "-c", script],
                cwd=REPOSITORY_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (home / ".azure" / "azureProfile.json").read_text(encoding="utf-8"),
                "profile",
            )
            self.assertEqual(
                (home / ".azure" / "msal_token_cache.bin").read_bytes(),
                b"token-cache",
            )
            self.assertIn("Azure CLI profile synchronized", result.stderr)

    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    def test_azure_cli_profile_sync_is_noop_without_cli_login(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            env = dict(os.environ)
            env.update(
                {
                    "HOME": str(home),
                    "AZ_CLI_LOGGED_IN": "0",
                    "QA_WSL_RUNTIME_PY": str(root / "unused.py"),
                }
            )
            env.pop("AZURE_CONFIG_DIR", None)
            script = f'''source "{WINDOWS_WSL_RUNTIME}"
qa_sync_azure_cli_profile_to_windows_home
'''

            result = subprocess.run(
                ["bash", "-c", script],
                cwd=REPOSITORY_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((home / ".azure").exists())


if __name__ == "__main__":
    unittest.main()
