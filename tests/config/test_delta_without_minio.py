from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/extensions.yml"
PREPARER = ROOT / "scripts/prepare-delta-local-tests.sh"
RUNNER = ROOT / "scripts/run-standard-tests.sh"

MINIO_ONLY = {
    "test/sql/cloud/minio_local/minio_local.test",
    "test/sql/cloud/minio_local/gcs_r2.test",
}


class DeltaLocalOnlyTests(unittest.TestCase):
    def test_only_minio_dependent_tests_are_explicitly_excluded(self) -> None:
        config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        delta = config["testBatteries"]["delta"]
        self.assertTrue(delta["isEnabled"])
        self.assertEqual(delta["profiles"][0]["tests"], "test/sql/*")
        skips = delta["ignoredTests"]
        self.assertEqual({item["path"] for item in skips}, MINIO_ONLY)
        self.assertTrue(all(item["profiles"] == ["all"] for item in skips))
        self.assertTrue(all("MinIO" in item["reason"] for item in skips))

    def test_preparer_preserves_local_fixtures_without_cloud_setup(self) -> None:
        script = PREPARER.read_text(encoding="utf-8")
        for required in (
            "cargo build --manifest-path",
            "generate-data unpack-golden-tables-release",
            'export GENERATED_DATA_AVAILABLE=1',
            'export GOLDEN_TABLES_PATH=',
            'export DELTA_KERNEL_TESTS_PATH=',
            'export DAT_PATH=',
            'unset S3_TEST_SERVER_AVAILABLE DUCKDB_MINIO_TEST_SERVER_AVAILABLE',
        ):
            self.assertIn(required, script)
        for unexpected in ("docker run", "docker rm", "awscli", "minio_s3.yml",
                           "upload_test_files_to_minio.sh", "/etc/hosts"):
            self.assertNotIn(unexpected, script)

    def test_runner_does_not_register_obsolete_minio_cleanup(self) -> None:
        script = RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("DELTA_MINIO_CONTAINER", script)
        self.assertIn('source "${DELTA_ENV_FILE}"', script)


if __name__ == "__main__":
    unittest.main()
