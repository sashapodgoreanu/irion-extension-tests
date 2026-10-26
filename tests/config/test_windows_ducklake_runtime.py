from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class WindowsDuckLakeRuntimeTest(unittest.TestCase):
    def test_ducklake_runner_uses_and_cleans_a_short_source_junction(self) -> None:
        runner = (ROOT / "scripts" / "run-windows-wsl-battery.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("Join-Path $sourceDriveRoot 'qa'", runner)
        self.assertIn("$runnerSourceRoot = $shortSourceAlias", runner)
        self.assertIn("& python $runner $BatteryName $runnerSourceRoot", runner)
        self.assertIn("removed DuckLake short source alias", runner)

    def test_ducklake_long_sqlite_metadata_path_stays_under_windows_max_path(self) -> None:
        sqlite_path = (
            r"D:\qa\duckdb_unittest_tempdir\2026-10-26T09-20-40Z--coral-rhombus-42"
            r"\test_sql_deletion_inlining_test_deletion_from_file_and_inserted_inlining_non_sequential_test"
            r"\test_sql_deletion_inlining_test_deletion_from_file_and_inserted_inlining_non_sequential.test.db"
        )
        self.assertLessEqual(len(sqlite_path) + 1, 260)

    def test_standard_runner_preserves_windows_junction_paths(self) -> None:
        runner = (ROOT / "scripts" / "run-standard-tests.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('if os.name == "nt":', runner)
        self.assertIn("upstream_root = upstream_root_arg.absolute()", runner)
        self.assertIn("upstream_root = upstream_root_arg.resolve()", runner)


if __name__ == "__main__":
    unittest.main()
