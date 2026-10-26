from __future__ import annotations

import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TestWindowsPostgresScannerAdapter(unittest.TestCase):
    def test_current_pinned_fixture_and_binary_paths_are_adapted(self) -> None:
        adapter = runpy.run_path(str(ROOT / "scripts" / "prepare-windows-test-source.py"))
        with tempfile.TemporaryDirectory() as directory:
            upstream = Path(directory)
            (upstream / "test" / "sql" / "misc").mkdir(parents=True)
            fixture = upstream / "create-postgres-tables.sh"
            fixture.write_text(
                """psql -d postgresscanner < ${ABS_DIR_PREFIX}/postgresscannertmp/schema.sql
sed -E "s/,\\s*allow_quoted_nulls\\s+[^,)]+//g" ${ABS_DIR_PREFIX}/postgresscannertmp/load.sql > ${ABS_DIR_PREFIX}/postgresscannertmp/load_filtered.sql
psql -d postgresscanner < ${ABS_DIR_PREFIX}/postgresscannertmp/load_filtered.sql
""",
                encoding="utf-8",
            )
            binary_test = upstream / "test" / "sql" / "misc" / "postgres_binary.test"
            binary_test.write_text(
                """CALL postgres_execute('s', 'COPY binary_copy_test FROM ''{WORKING_DIRECTORY}/{TEST_DIR}/pg_binary.bin'' (FORMAT binary)')
CALL postgres_execute('s', 'COPY binary_copy_test FROM ''{WORKING_DIRECTORY}/{TEST_DIR}/pg_binary.bin'' (FORMAT binary)')
""",
                encoding="utf-8",
            )

            adapter["patch_postgres_scanner"](upstream)

            adapted_fixture = fixture.read_text(encoding="utf-8")
            self.assertIn('WINDOWS_ABS_DIR_PREFIX="$(wslpath -m "${ABS_DIR_PREFIX}")"', adapted_fixture)
            self.assertIn('"${ABS_DIR_PREFIX}/postgresscannertmp/load_filtered.sql"', adapted_fixture)
            self.assertIn("psql -d postgresscanner < ${ABS_DIR_PREFIX}/postgresscannertmp/load_filtered.sql", adapted_fixture)
            adapted_test = binary_test.read_text(encoding="utf-8")
            self.assertEqual(adapted_test.count("replace("), 2)
            self.assertIn(f"{upstream.as_posix()}/{{TEST_DIR}}/pg_binary.bin", adapted_test)
            self.assertNotIn("{WORKING_DIRECTORY}/{TEST_DIR}", adapted_test)


if __name__ == "__main__":
    unittest.main()
