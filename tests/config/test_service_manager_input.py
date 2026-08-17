from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SERVICE_MANAGER = REPOSITORY_ROOT / "scripts" / "service-manager.sh"


class ServiceManagerInputTestCase(unittest.TestCase):
    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    def test_child_process_cannot_consume_remaining_service_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "services.json"
            manifest.write_text(
                json.dumps(
                    [
                        {"name": "first", "type": "python-http", "port": 9001},
                        {"name": "second", "type": "python-http", "port": 9002},
                        {"name": "third", "type": "python-http", "port": 9003},
                    ]
                ),
                encoding="utf-8",
            )
            started = root / "started.txt"
            script = f'''source "{SERVICE_MANAGER}"
STARTED="{started}"
qa_service_start_python_http() {{
  if [[ "$1" == "first" ]]; then
    cat >/dev/null
  fi
  printf '%s:%s\\n' "$1" "$2" >>"$STARTED"
}}
qa_service_start_file "{manifest}"
'''

            result = subprocess.run(
                ["bash", "-c", script],
                cwd=REPOSITORY_ROOT,
                input="caller-input\n",
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                started.read_text(encoding="utf-8").splitlines(),
                ["first:9001", "second:9002", "third:9003"],
            )
            self.assertIn("count=3", result.stderr)
            self.assertIn("ready name=third type=python-http", result.stderr)


if __name__ == "__main__":
    unittest.main()
