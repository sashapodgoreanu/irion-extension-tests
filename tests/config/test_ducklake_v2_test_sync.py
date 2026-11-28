"""Regression coverage for official DuckLake v2.0 SQL fixture synchronization."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/sync-ducklake-v2-tests.py"
spec = importlib.util.spec_from_file_location("ducklake_test_sync", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# Original fixture bytes from the immutable DuckLake binary's source pin.
OLD_FIXTURES = json.loads("{\"test/sql/catalog/nested_schema/drop_macro_used_by_table.test\":\"# name: test/sql/catalog/nested_schema/drop_macro_used_by_table.test\\n# description: DROP MACRO of a nested schema is refused while a column default calls the macro by its full path\\n# group: [nested_schema]\\n\\nrequire ducklake\\n\\nrequire parquet\\n\\ntest-env DUCKLAKE_CONNECTION {TEST_DIR}/{UUID}.db\\n\\ntest-env DATA_PATH {TEST_DIR}\\n\\nstatement ok\\nATTACH 'ducklake:{DUCKLAKE_CONNECTION}' AS lake (DATA_PATH '{DATA_PATH}/nested_drop_macro_used_by_table', DUCKLAKE_VERSION '1.1')\\n\\nstatement ok\\nCREATE SCHEMA lake.a\\n\\nstatement ok\\nCREATE SCHEMA lake.a.b\\n\\nstatement ok\\nCREATE SCHEMA lake.c\\n\\nstatement ok\\nCREATE SCHEMA lake.c.b\\n\\nstatement ok\\nCREATE MACRO lake.a.b.f() AS 1\\n\\nstatement ok\\nCREATE MACRO lake.c.b.f() AS 2\\n\\nstatement ok\\nCREATE TABLE lake.y (c INTEGER DEFAULT lake.a.b.f())\\n\\n# a macro of the same name in another schema is held too\\nstatement error\\nDROP MACRO lake.c.b.f\\n----\\nCannot drop macro \\\"f\\\" because the default of column \\\"c\\\" of table \\\"y\\\" calls it\\n\\nstatement error\\nDROP MACRO lake.a.b.f\\n----\\nCannot drop macro \\\"f\\\" because the default of column \\\"c\\\" of table \\\"y\\\" calls it\\n\\n# catalog.name in a table of a nested schema resolves through the name of its schema\\nstatement ok\\nCREATE SCHEMA lake.b\\n\\nstatement ok\\nCREATE MACRO lake.b.k() AS 9\\n\\nstatement ok\\nCREATE TABLE lake.a.b.t (c INTEGER DEFAULT lake.k())\\n\\nstatement ok\\nINSERT INTO lake.a.b.t DEFAULT VALUES\\n\\nquery I\\nSELECT c FROM lake.a.b.t\\n----\\n9\\n\\nstatement error\\nDROP MACRO lake.b.k\\n----\\nCannot drop macro \\\"k\\\" because the default of column \\\"c\\\" of table \\\"t\\\" calls it\\n\",\"test/sql/catalog/nested_schema/nested_schema_version_gate.test\":\"# name: test/sql/catalog/nested_schema/nested_schema_version_gate.test\\n# description: Nested schemas require DuckLake 1.1 metadata\\n# group: [nested_schema]\\n\\nrequire ducklake\\n\\nrequire parquet\\n\\ntest-env DUCKLAKE_CONNECTION {TEST_DIR}/{UUID}.db\\n\\ntest-env DATA_PATH {TEST_DIR}\\n\\nstatement ok\\nATTACH 'ducklake:{DUCKLAKE_CONNECTION}' AS ducklake (DATA_PATH '{DATA_PATH}/nested_gate_files', DUCKLAKE_VERSION '1.0')\\n\\nstatement ok\\nCREATE SCHEMA ducklake.s1;\\n\\nstatement error\\nCREATE SCHEMA ducklake.s1.child;\\n----\\nDuckLake 1.0 does not support nested schemas\\n\\nquery I\\nSELECT schema_name FROM duckdb_schemas() WHERE database_name = 'ducklake' ORDER BY ALL\\n----\\nmain\\ns1\\n\"}")


class DuckLakeV2FixtureSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for relpath, contents in OLD_FIXTURES.items():
            target = self.root / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")

    def test_exact_official_upstream_test_fixes(self) -> None:
        outcomes = module.adapt(self.root, verify_checkout=False)
        self.assertEqual(len(outcomes), 2)
        self.assertTrue(all(x.endswith(": synchronized") for x in outcomes))
        for fixture in module.SOURCE_FIXTURES:
            content = (self.root / fixture["path"]).read_bytes()
            self.assertEqual(module.git_blob_sha(content), fixture["revised"])
            self.assertEqual(content.decode("utf-8"), fixture["replacement"])
        fixed_macro = (self.root / module.SOURCE_FIXTURES[0]["path"]).read_text(encoding="utf-8")
        self.assertIn("CREATE MACRO lake.a.b.k() AS 9", fixed_macro)
        self.assertIn("DROP MACRO lake.a.b.k", fixed_macro)
        self.assertIn("Scalar Function with name k does not exist", fixed_macro)
        self.assertIn("CREATE TABLE lake.a.b.t (c INTEGER DEFAULT lake.k())", fixed_macro)
        self.assertEqual(
            module.adapt(self.root, verify_checkout=False),
            [f"{item['path']}: already synchronized" for item in module.SOURCE_FIXTURES],
        )

    def test_fail_closed_on_modified_upstream_fixture(self) -> None:
        fixture = module.SOURCE_FIXTURES[0]
        target = self.root / fixture["path"]
        target.write_text(target.read_text(encoding="utf-8") + "-- unexpected mutation\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "pinned fixture changed"):
            module.adapt(self.root, verify_checkout=False)

    def test_runner_is_linux_v2_only_and_never_skips_tests(self) -> None:
        runner = (ROOT / "scripts/run-standard-tests.sh").read_text(encoding="utf-8")
        self.assertIn('if [[ "${TEST_NAME}" == "ducklake" ]]; then', runner)
        self.assertIn('if [[ "${DUCKDB_VERSION}" != "v2.0.1" ]]; then', runner)
        self.assertIn('python3 "${SCRIPT_DIR}/sync-ducklake-v2-tests.py" "${UPSTREAM_ROOT}"', runner)
        self.assertNotIn("skip_tests", SCRIPT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
