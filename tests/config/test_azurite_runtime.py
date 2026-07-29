from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from qa import load_config, resolve_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPOSITORY_ROOT / "config" / "extensions.yml"
PREPARE_BATTERY = REPOSITORY_ROOT / "scripts" / "prepare-test-battery.py"
SERVICE_MANAGER = REPOSITORY_ROOT / "scripts" / "service-manager.sh"
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "extension-qa.yml"


class AzuriteRuntimeTestCase(unittest.TestCase):
    def test_azure_service_reaches_runtime_manifest_and_ci(self) -> None:
        plan = resolve_config(load_config(CONFIG_PATH))
        azure = next(item for item in plan.matrix()["include"] if item["name"] == "azure")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "azure.json"
            output = root / "runtime"
            source.write_text(json.dumps(azure), encoding="utf-8")
            subprocess.run(
                [sys.executable, str(PREPARE_BATTERY), str(source), str(output)],
                check=True,
                cwd=REPOSITORY_ROOT,
            )
            self.assertEqual(
                json.loads((output / "services.json").read_text(encoding="utf-8")),
                [{"name": "storage-emulator", "type": "azurite", "port": 10000}],
            )
            self.assertEqual(
                json.loads((output / "capabilities.json").read_text(encoding="utf-8")),
                ["azurite"],
            )

        manager = SERVICE_MANAGER.read_text(encoding="utf-8")
        self.assertIn("qa_service_start_azurite", manager)
        self.assertIn("upload_test_files_to_azurite.sh", manager)
        self.assertIn("AZURE_STORAGE_CONNECTION_STRING", manager)

        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("contains(matrix.capabilities, 'azurite')", workflow)
        self.assertIn("npm install --global azurite", workflow)


if __name__ == "__main__":
    unittest.main()
