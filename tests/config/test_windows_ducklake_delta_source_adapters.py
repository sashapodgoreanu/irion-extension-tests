from __future__ import annotations

import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TestWindowsDuckLakeSourceAdapter(unittest.TestCase):
    def test_pinned_metadata_test_already_checks_its_own_database(self) -> None:
        adapter = runpy.run_path(str(ROOT / "scripts" / "prepare-windows-test-source.py"))
        body = """test-env DUCKLAKE_CONNECTION {TEST_DIR}/metadata_in_data_path_{UUID}.db
test-env DATA_PATH {TEST_DIR}

query I
SELECT count(*) FROM GLOB('{DATA_PATH}/metadata_in_data_path_*.db')
----
1

query I
SELECT count(*) FROM GLOB('{DATA_PATH}/metadata_in_data_path_*.db')
----
1
"""
        with tempfile.TemporaryDirectory() as directory:
            upstream = Path(directory)
            test = upstream / "test/sql/remove_orphans/metadata_in_data_path.test"
            test.parent.mkdir(parents=True)
            test.write_text(body, encoding="utf-8")

            adapter["patch_ducklake"](upstream)

            self.assertEqual(test.read_text(encoding="utf-8"), body)

    def test_legacy_wildcard_counts_are_scoped_to_ducklake_connection(self) -> None:
        adapter = runpy.run_path(str(ROOT / "scripts" / "prepare-windows-test-source.py"))
        old = "SELECT count(*) FROM GLOB('${DATA_PATH}/*.db')"
        body = f"{old}\n{old}\n"
        with tempfile.TemporaryDirectory() as directory:
            upstream = Path(directory)
            test = upstream / "test/sql/remove_orphans/metadata_in_data_path.test"
            test.parent.mkdir(parents=True)
            test.write_text(body, encoding="utf-8")

            adapter["patch_ducklake"](upstream)

            updated = test.read_text(encoding="utf-8")
            self.assertEqual(updated.count("regexp_replace('${DUCKLAKE_CONNECTION}'"), 2)
            self.assertNotIn(old, updated)


class TestWindowsDeltaMakefileAdapter(unittest.TestCase):
    def test_current_pinned_makefile_keeps_fixture_symlinks_windows_readable(self) -> None:
        adapter = runpy.run_path(str(ROOT / "scripts" / "prepare-windows-test-source.py"))
        makefile = """generate-data:
	${PIP} install delta-spark==4.0.0
	python3 scripts/data_generator/generate_test_data.py

unpack-golden-tables-release:
	./scripts/unwrap_golden_tables.sh
"""
        with tempfile.TemporaryDirectory() as directory:
            upstream = Path(directory)
            (upstream / "Makefile").write_text(makefile, encoding="utf-8")
            test = upstream / "test/sql/generated/basic.test"
            test.parent.mkdir(parents=True)
            test.write_text(
                "statement ok\nfrom copy_dir('data/generated/simple', '__TEST_DIR__/simple');\n",
                encoding="utf-8",
            )

            adapter["patch_delta"](upstream)

            updated = (upstream / "Makefile").read_text(encoding="utf-8")
            self.assertIn("find build/release/rust/src/delta_kernel/acceptance/tests/dat -type l", updated)
            self.assertIn("find data/unpacked_golden_tables -type l", updated)
            self.assertNotIn("chmod a-w", updated)


if __name__ == "__main__":
    unittest.main()
