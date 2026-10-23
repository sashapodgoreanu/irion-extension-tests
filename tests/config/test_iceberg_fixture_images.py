from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATCHER = ROOT / "scripts" / "patch-iceberg-fixture.py"
RUNNER = ROOT / "scripts" / "run-test-battery.sh"

ORIGINAL = """services:
  rest:
    image: apache/iceberg-rest-fixture:1.10.1
  minio:
    image: minio/minio
  mc:
    image: minio/mc
"""


class IcebergFixtureImageTest(unittest.TestCase):
    def test_pinned_images_are_substituted_once_and_rerunnable(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            compose = Path(folder) / "scripts" / "docker-compose.yml"
            compose.parent.mkdir()
            compose.write_text(ORIGINAL, encoding="utf-8")
            for _ in range(2):
                result = subprocess.run(
                    [sys.executable, str(PATCHER), folder],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            content = compose.read_text(encoding="utf-8")
            self.assertIn(
                "image: dappros/minio:RELEASE.2025-09-07T16-13-09Z", content
            )
            self.assertIn(
                "image: ghcr.io/golithus/mc:RELEASE.2025-08-13T08-35-41Z",
                content,
            )
            self.assertIn("image: apache/iceberg-rest-fixture:1.10.1", content)
            self.assertNotIn("image: minio/minio", content)
            self.assertNotIn("image: minio/mc", content)

    def test_upstream_image_drift_fails_without_partial_edits(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            compose = Path(folder) / "scripts" / "docker-compose.yml"
            compose.parent.mkdir()
            altered = ORIGINAL.replace("image: minio/mc", "image: another/mc")
            compose.write_text(altered, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(PATCHER), folder],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Unexpected Iceberg fixture image", result.stderr)
            self.assertEqual(compose.read_text(encoding="utf-8"), altered)

    def test_adapter_is_invoked_before_running_iceberg_fixture(self) -> None:
        script = RUNNER.read_text(encoding="utf-8")
        self.assertIn('if [[ "${BATTERY_NAME}" == "iceberg" ]]; then', script)
        self.assertIn('patch-iceberg-fixture.py', script)
        self.assertLess(
            script.index('patch-iceberg-fixture.py'),
            script.index('qa_log INFO "executing runner kind=${RUNNER_KIND}"'),
        )


if __name__ == "__main__":
    unittest.main()
