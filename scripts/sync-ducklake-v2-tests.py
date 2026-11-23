#!/usr/bin/env python3
"""Synchronize two DuckLake v2.0.1 SQL tests with upstream v2.0 branch fixes.

The official signed DuckLake binary for DuckDB v2.0.1 reports the source
revision 08089b16dc8a18ce04abb6efd87e25cb4d64803a, whose SQL tests predate upstream DuckDB v2.0 fixes.

The upstream v2.0-cyanoptera branch integrated the exact two corrections in
duckdb/ducklake@bc9e351d700844f643bbe4b233839f6e58518886 on 2026-11-20:
- drop_macro_used_by_table.test now verifies the *full* nested schema path,
  the failure to resolve an identically named top-level schema's macro,
  the successful nested macro resolution, and both DROP dependency checks.
- nested_schema_version_gate.test matches the engine's current error text
  while still asserting DuckLake 1.0 rejects nested schema creation.

Only replace the two known, pinned source test files with exact official
upstream versions; keep their original binary/source SHA pins unchanged.
Fail closed if either source file changed. No test is skipped or removed.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

SOURCE_SHA = "08089b16dc8a18ce04abb6efd87e25cb4d64803a"
FIXED_TESTS_COMMIT = "bc9e351d700844f643bbe4b233839f6e58518886"
# (path, expected original Git blob SHA, expected upstream-fixed blob SHA, replacement text)
SOURCE_FIXTURES = json.loads("[{\"path\":\"test/sql/catalog/nested_schema/drop_macro_used_by_table.test\",\"original\":\"65cd6957f5d72d98a2feb3b6836dc560f1feada4\",\"revised\":\"8c526490a7d267fc5d27df333bf432df372d0116\",\"replacement\":\"# name: test/sql/catalog/nested_schema/drop_macro_used_by_table.test\\n# description: DROP MACRO of a nested schema is refused while a column default calls the macro by its full path\\n# group: [nested_schema]\\n\\nrequire ducklake\\n\\nrequire parquet\\n\\ntest-env DUCKLAKE_CONNECTION {TEST_DIR}/{UUID}.db\\n\\ntest-env DATA_PATH {TEST_DIR}\\n\\nstatement ok\\nATTACH 'ducklake:{DUCKLAKE_CONNECTION}' AS lake (DATA_PATH '{DATA_PATH}/nested_drop_macro_used_by_table', DUCKLAKE_VERSION '1.1')\\n\\nstatement ok\\nCREATE SCHEMA lake.a\\n\\nstatement ok\\nCREATE SCHEMA lake.a.b\\n\\nstatement ok\\nCREATE SCHEMA lake.c\\n\\nstatement ok\\nCREATE SCHEMA lake.c.b\\n\\nstatement ok\\nCREATE MACRO lake.a.b.f() AS 1\\n\\nstatement ok\\nCREATE MACRO lake.c.b.f() AS 2\\n\\nstatement ok\\nCREATE TABLE lake.y (c INTEGER DEFAULT lake.a.b.f())\\n\\n# a macro of the same name in another schema is held too\\nstatement error\\nDROP MACRO lake.c.b.f\\n----\\nCannot drop macro \\\"f\\\" because the default of column \\\"c\\\" of table \\\"y\\\" calls it\\n\\nstatement error\\nDROP MACRO lake.a.b.f\\n----\\nCannot drop macro \\\"f\\\" because the default of column \\\"c\\\" of table \\\"y\\\" calls it\\n\\n# catalog.name in a table of a nested schema resolves through the full path of its schema\\nstatement ok\\nCREATE SCHEMA lake.b\\n\\nstatement ok\\nCREATE MACRO lake.b.k() AS 1\\n\\n# the top-level schema b of the same name is not searched\\nstatement error\\nCREATE TABLE lake.a.b.t (c INTEGER DEFAULT lake.k())\\n----\\nScalar Function with name k does not exist\\n\\nstatement ok\\nCREATE MACRO lake.a.b.k() AS 9\\n\\nstatement ok\\nCREATE TABLE lake.a.b.t (c INTEGER DEFAULT lake.k())\\n\\nstatement ok\\nINSERT INTO lake.a.b.t DEFAULT VALUES\\n\\nquery I\\nSELECT c FROM lake.a.b.t\\n----\\n9\\n\\n# a macro of the same name in another schema is held too\\nstatement error\\nDROP MACRO lake.b.k\\n----\\nCannot drop macro \\\"k\\\" because the default of column \\\"c\\\" of table \\\"t\\\" calls it\\n\\nstatement error\\nDROP MACRO lake.a.b.k\\n----\\nCannot drop macro \\\"k\\\" because the default of column \\\"c\\\" of table \\\"t\\\" calls it\\n\"},{\"path\":\"test/sql/catalog/nested_schema/nested_schema_version_gate.test\",\"original\":\"9aa43f48934be57a9c6a706a043d91facbe5d308\",\"revised\":\"067ea44dd74569a82dd7d503e88bec918b8066bc\",\"replacement\":\"# name: test/sql/catalog/nested_schema/nested_schema_version_gate.test\\n# description: Nested schemas require DuckLake 1.1 metadata\\n# group: [nested_schema]\\n\\nrequire ducklake\\n\\nrequire parquet\\n\\ntest-env DUCKLAKE_CONNECTION {TEST_DIR}/{UUID}.db\\n\\ntest-env DATA_PATH {TEST_DIR}\\n\\nstatement ok\\nATTACH 'ducklake:{DUCKLAKE_CONNECTION}' AS ducklake (DATA_PATH '{DATA_PATH}/nested_gate_files', DUCKLAKE_VERSION '1.0')\\n\\nstatement ok\\nCREATE SCHEMA ducklake.s1;\\n\\nstatement error\\nCREATE SCHEMA ducklake.s1.child;\\n----\\ndoes not support nested schemas\\n\\nquery I\\nSELECT schema_name FROM duckdb_schemas() WHERE database_name = 'ducklake' ORDER BY ALL\\n----\\nmain\\ns1\\n\"}]")


def git_blob_sha(data: bytes) -> str:
    header = b"blob " + str(len(data)).encode("ascii") + b"\0"
    return hashlib.sha1(header + data).hexdigest()


def replace_fixture(path: Path, old_sha: str, new_sha: str, replacement: str) -> str:
    if not path.is_file():
        raise RuntimeError(f"DuckLake SQL fixture is missing: {path}")
    before = path.read_bytes()
    actual = git_blob_sha(before)
    revised = replacement.encode("utf-8")
    if git_blob_sha(revised) != new_sha:
        raise RuntimeError(f"Embedded official upstream fixture is corrupt: {path}")
    if actual == new_sha:
        return "already synchronized"
    if actual != old_sha:
        raise RuntimeError(
            f"DuckLake pinned fixture changed: {path} (expected {old_sha}, got {actual})"
        )
    path.write_bytes(revised)
    if git_blob_sha(path.read_bytes()) != new_sha:
        raise RuntimeError(f"DuckLake fixture synchronization failed: {path}")
    return "synchronized"


def adapt(upstream_root: Path, *, verify_checkout: bool = True) -> list[str]:
    if verify_checkout:
        current = subprocess.check_output(
            ["git", "-C", str(upstream_root), "rev-parse", "HEAD"],
            text=True,
            timeout=15,
        ).strip()
        if current != SOURCE_SHA:
            raise RuntimeError(f"DuckLake source pin mismatch: expected {SOURCE_SHA}, got {current}")
    outcomes = []
    for fixture in SOURCE_FIXTURES:
        path = upstream_root / fixture["path"]
        status = replace_fixture(
            path, fixture["original"], fixture["revised"], fixture["replacement"]
        )
        outcomes.append(f"{fixture['path']}: {status}")
    return outcomes


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: sync-ducklake-v2-tests.py <pinned-upstream-root>")
    for outcome in adapt(Path(sys.argv[1])):
        print("DuckLake v2.0.1: " + outcome)
