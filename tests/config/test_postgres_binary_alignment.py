"""Keep PostgreSQL scanner SQLLogicTests aligned with the DuckDB binary."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE_COMMIT = "c0f5a3c0c4b68b02afbf669d36d7f0e503985c88"
BINARY_PREFIX = "c0f5a3c0c4"


class PostgresScannerBinaryAlignmentTest(unittest.TestCase):
    def test_postgres_scanner_source_matches_distributed_binary(self) -> None:
        config = yaml.safe_load(
            (ROOT / "config/extensions.yml").read_text(encoding="utf-8")
        )
        scanner = config["testBatteries"]["postgres_scanner"]
        self.assertTrue(scanner["isEnabled"])
        self.assertEqual(scanner["repository"], "duckdb/duckdb-postgres")
        self.assertEqual(scanner["pin"], SOURCE_COMMIT)
        self.assertTrue(SOURCE_COMMIT.startswith(BINARY_PREFIX))

    def test_runtime_keeps_strict_source_binary_alignment_check(self) -> None:
        runner = (ROOT / "scripts/run-postgres-scanner-tests.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("Postgres scanner source/binary commit mismatch:", runner)
        self.assertIn('expected_commit.startswith(reported_commit)', runner)
        self.assertIn("raise SystemExit(", runner)
        self.assertIn('ACTUAL_COMMIT="$(git -C "${UPSTREAM_ROOT}" rev-parse HEAD)"', runner)
        self.assertIn('if [[ "${ACTUAL_COMMIT}" != "${EXPECTED_COMMIT}" ]]', runner)


if __name__ == "__main__":
    unittest.main()
