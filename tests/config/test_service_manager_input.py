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
    def test_httpfs_minio_fixture_rewrites_only_pinned_unavailable_images(self) -> None:
        original = (
            "services:\\n"
            "  minio:\\n"
            "    image: minio/minio:RELEASE.2025-09-07T16-13-09Z-cpuv1\\n"
            "  minio_setup:\\n"
            "    image: minio/mc:RELEASE.2025-08-13T08-35-41Z-cpuv1\\n"
        )
        command = 'source "$1"; qa_httpfs_rewrite_minio_images "$2"'
        with tempfile.TemporaryDirectory() as directory:
            compose = Path(directory) / "minio_s3.yml"
            compose.write_text(original, encoding="utf-8")
            result = subprocess.run(
                ["bash", "-c", command, "bash", str(SERVICE_MANAGER), str(compose)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            patched = compose.read_text(encoding="utf-8")
            self.assertIn(
                "image: dappros/minio:RELEASE.2025-09-07T16-13-09Z",
                patched,
            )
            self.assertIn(
                "image: ghcr.io/golithus/mc:RELEASE.2025-08-13T08-35-41Z",
                patched,
            )
            self.assertNotIn("image: minio/mc:", patched)

            # If upstream updates its fixture, do not silently keep old mirrors.
            compose.write_text(original.replace("cpuv1", "changed"), encoding="utf-8")
            rejected = subprocess.run(
                ["bash", "-c", command, "bash", str(SERVICE_MANAGER), str(compose)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("versions have changed", rejected.stderr)


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
