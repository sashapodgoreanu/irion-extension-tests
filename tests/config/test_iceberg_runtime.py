from __future__ import annotations

import unittest
from pathlib import Path

from qa import load_config, resolve_config

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "extensions.yml"
ICEBERG_COMMIT = "45163a28e0ed6a2071a82a1bf1dd432d0216cf9c"
IGNORED_METADATA_TESTS = [
    "test/sql/local/iceberg_scans/iceberg_partition_stats.test",
    "test/sql/local/iceberg_scans/iceberg_column_stats.test",
]


class IcebergRuntimeTest(unittest.TestCase):
    def test_iceberg_profile_is_strict_and_has_complete_local_fixtures(self) -> None:
        plan = resolve_config(load_config(CONFIG_PATH))
        matrix_case = next(
            item for item in plan.matrix()["include"] if item["name"] == "iceberg"
        )
        self.assertEqual(matrix_case["pin"], ICEBERG_COMMIT)
        self.assertEqual(matrix_case["prerequisites"], [])
        self.assertEqual(matrix_case["capabilities"], [])
        self.assertEqual([profile["name"] for profile in matrix_case["profiles"]], ["all"])
        self.assertEqual(
            [item["path"] for item in matrix_case["ignoredTests"]],
            IGNORED_METADATA_TESTS,
        )
        for item in matrix_case["ignoredTests"]:
            self.assertIn("verify-iceberg-metadata.py", item["reason"])

        runner = (ROOT / "scripts/run-standard-tests.sh").read_text(encoding="utf-8")
        preparer = (ROOT / "scripts/prepare-iceberg-local-tests.sh").read_text(
            encoding="utf-8"
        )
        verifier = (ROOT / "scripts/verify-iceberg-metadata.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('TEST_NAME}" == "iceberg"', runner)
        self.assertIn("prepare-iceberg-local-tests.sh", runner)
        self.assertIn("test/configs/fixture.json", runner)
        self.assertIn("catalog_test_config_setup", runner)
        self.assertIn("catalog_custom_setup/fixture", runner)

        for upstream_contract in (
            "fixture-data-local",
            "fixture-data",
            "fixture-stop",
            "scripts/docker-compose.yml",
            "scripts/requirements.txt",
            "vended_credentials_refresh_proxy.py",
        ):
            self.assertIn(upstream_contract, preparer)
        self.assertIn("DUCKDB_ICEBERG_HAVE_GENERATED_DATA=1", preparer)
        self.assertIn("FIXTURE_SERVER_AVAILABLE=1", preparer)
        self.assertIn("HTTP_PROXY_PUBLIC=http://localhost:8878", preparer)
        self.assertIn("VENDED_CREDENTIAL_REFRESH_PROXY=http://127.0.0.1:19133", preparer)

        self.assertIn("verify-iceberg-metadata.py", runner)
        self.assertIn('"partition_stats": 3', verifier)
        self.assertIn('"column_stats": 18', verifier)
        self.assertIn("LOAD iceberg;", verifier)


if __name__ == "__main__":
    unittest.main()
