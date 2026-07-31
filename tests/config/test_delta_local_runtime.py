from __future__ import annotations

import unittest
from pathlib import Path

from qa import load_config, resolve_config

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "extensions.yml"
DELTA_COMMIT = "45c40878601b54b4188b09e08732fe0d576ad222"


class DeltaLocalRuntimeTest(unittest.TestCase):
    def test_delta_local_runtime_follows_upstream_contracts(self) -> None:
        plan = resolve_config(load_config(CONFIG_PATH))
        matrix_case = next(
            item for item in plan.matrix()["include"] if item["name"] == "delta"
        )
        self.assertEqual(matrix_case["pin"], DELTA_COMMIT)
        self.assertEqual(matrix_case["prerequisites"], [])
        self.assertEqual([profile["name"] for profile in matrix_case["profiles"]], ["all"])

        runner = (ROOT / "scripts/run-standard-tests.sh").read_text(encoding="utf-8")
        preparer = (ROOT / "scripts/prepare-delta-local-tests.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('TEST_NAME}" == "delta"', runner)
        self.assertIn("prepare-delta-local-tests.sh", runner)
        self.assertIn("DELTA_MINIO_CONTAINER", runner)

        for upstream_contract in (
            "generate-data",
            "unpack-golden-tables-release",
            "DELTA_KERNEL_TESTS_PATH",
            "DAT_PATH",
            "GIT_REPOSITORY",
            "GIT_TAG",
            "scripts/env_minio",
            "scripts/create_minio_credential_file.sh",
            "scripts/upload_test_files_to_minio.sh",
        ):
            self.assertIn(upstream_contract, preparer)

        self.assertIn("cargo build --manifest-path", preparer)
        self.assertIn("GENERATED_DATA_AVAILABLE=1", preparer)
        self.assertIn("GOLDEN_TABLES_PATH", preparer)
        self.assertIn("DUCKDB_MINIO_TEST_SERVER_AVAILABLE=1", preparer)
        self.assertIn("raw.githubusercontent.com/duckdb/duckdb-httpfs", preparer)

        # Real cloud credentials remain intentionally outside the local profile.
        self.assertNotIn("export AZURE_CLIENT_ID", preparer)
        self.assertNotIn("export AZURE_CLIENT_SECRET", preparer)
        self.assertNotIn("export GENERATED_S3_DATA_AVAILABLE", preparer)


if __name__ == "__main__":
    unittest.main()
