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
    def test_native_temp_uses_shared_path_without_forwarding_wsl_tmpdir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = dict(os.environ)
            env.update(
                {
                    "HOME": str(root / "home"),
                    "TMPDIR": "/tmp/linux-only",
                    "QA_WINDOWS_TEMP_DIR": "/mnt/d/shared/.qa-unity",
                    "QA_WSL_RUNTIME_PY": str(root / "unused.py"),
                    "WSLENV": "KEEP:TMPDIR/p:KEEP_PATH/p",
                }
            )
            script = f'''source "{WINDOWS_WSL_RUNTIME}"
qa_prepare_windows_environment
printf '%s\\n' "$TEMP" "$TMP" "$WSLENV"
'''

            result = subprocess.run(
                ["bash", "-c", script],
                cwd=REPOSITORY_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines()[:2], ["/mnt/d/shared/.qa-unity"] * 2)
            wslenv = result.stdout.splitlines()[2].split(":")
            self.assertIn("KEEP", wslenv)
            self.assertIn("KEEP_PATH/p", wslenv)
            self.assertIn("TEMP/p", wslenv)
            self.assertIn("TMP/p", wslenv)
            self.assertFalse(any(entry.startswith("TMPDIR") for entry in wslenv))

    def test_linux_null_device_is_translated_for_native_windows_tools(self) -> None:
        helper = REPOSITORY_ROOT / "scripts" / "windows-wsl-runtime.py"
        result = subprocess.run(
            ["python3", str(helper), "translate-text", ".output /dev/null"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, ".output NUL")

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
