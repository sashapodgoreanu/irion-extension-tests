#!/usr/bin/env python3
"""Apply deterministic SQLLogicTest fixes to the pinned MSSQL v0.2.1 checkout.

The v0.2.1 release predates the first upstream CI execution of test/sql/*.test.
When upstream enabled the suite in issue #192, it found several test-side
inconsistencies: CALL used for the scalar mssql_exec function, stale pool-stat
column names, and BIGINT-to-INT success expectations that contradict the
release's widening-only type validator.

This script patches only the temporary upstream checkout used by CI. It does not
modify the published MSSQL binary and it deliberately fails when the expected
v0.2.1 text is no longer present, forcing an explicit review when the release pin
is advanced.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

PATCH_CONTRACT = "mssql-v0.2.1-sqllogictest-fixes-v1"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_text(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"Expected upstream test file is missing: {path}")
    return path.read_text(encoding="utf-8")


def write_change(path: Path, before: str, after: str, labels: list[str], report: list[dict[str, Any]]) -> None:
    if before == after:
        return
    path.write_text(after, encoding="utf-8")
    report.append(
        {
            "path": path.as_posix(),
            "before_sha256": sha256_text(before),
            "after_sha256": sha256_text(after),
            "changes": labels,
        }
    )


def replace_exact(text: str, old: str, new: str, *, label: str, expected: int = 1) -> tuple[str, str]:
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"Patch contract mismatch for {label}: expected {expected} occurrence(s), found {count}"
        )
    return text.replace(old, new), f"{label} ({count})"


def patch_scalar_calls(test_root: Path, report: list[dict[str, Any]]) -> int:
    pattern = re.compile(r"(?im)^([ \t]*)CALL([ \t]+)mssql_exec\(")
    total = 0
    for path in sorted(test_root.rglob("*.test*")):
        before = read_text(path)
        after, count = pattern.subn(lambda match: f"{match.group(1)}SELECT{match.group(2)}mssql_exec(", before)
        if count:
            total += count
            write_change(path, before, after, [f"CALL mssql_exec -> SELECT mssql_exec ({count})"], report)
    if total == 0:
        raise SystemExit("Patch contract mismatch: no CALL mssql_exec statements were found")
    return total


def patch_copy_type_mismatch(path: Path, report: list[dict[str, Any]]) -> None:
    before = read_text(path)
    text = before
    labels: list[str] = []

    text, label = replace_exact(
        text,
        """# COPY should succeed (BIGINT to INT is compatible)\nstatement ok\nCOPY bigint_source TO 'db.dbo.int_target' (FORMAT 'bcp', CREATE_TABLE false);""",
        """# BIGINT to INT is a narrowing conversion and must be rejected.\nstatement error\nCOPY bigint_source TO 'db.dbo.int_target' (FORMAT 'bcp', CREATE_TABLE false);\n----\ntype mismatch\n\n# Explicit INTEGER casting is the supported success path.\nstatement ok\nCOPY (SELECT id::INTEGER AS id FROM bigint_source) TO 'db.dbo.int_target' (FORMAT 'bcp', CREATE_TABLE false);""",
        label="copy_type_mismatch narrowing contract",
    )
    labels.append(label)

    text, label = replace_exact(
        text,
        "CREATE TABLE date_source AS SELECT CURRENT_DATE AS date_col FROM range(3) t(i);",
        "CREATE TABLE date_source AS SELECT DATE '2024-01-15' AS date_col FROM range(3) t(i);",
        label="copy_type_mismatch DATE literal",
    )
    labels.append(label)

    write_change(path, before, text, labels, report)


def patch_copy_existing_temp(path: Path, report: list[dict[str, Any]]) -> None:
    before = read_text(path)
    text = before
    labels: list[str] = []

    text, label = replace_exact(
        text,
        """# Copy BIGINT to INT - should use target column metadata\nstatement ok\nCOPY local_test TO 'mssql://db/#temp_int' (FORMAT 'bcp', CREATE_TABLE false);""",
        """# Use an explicitly compatible INTEGER source for the successful path.\nstatement ok\nCREATE TABLE local_test_int AS SELECT id::INTEGER AS id FROM local_test;\n\nstatement ok\nCOPY local_test_int TO 'mssql://db/#temp_int' (FORMAT 'bcp', CREATE_TABLE false);""",
        label="copy_existing_temp compatible INT source",
    )
    labels.append(label)

    text, label = replace_exact(
        text,
        """COPY local_test_int TO 'mssql://db/#temp_int' (FORMAT 'bcp', CREATE_TABLE false);\n\nquery I\nSELECT COUNT(*) FROM mssql_scan('db', 'SELECT * FROM #temp_int');\n----\n10\n\nstatement ok\nROLLBACK;""",
        """COPY local_test_int TO 'mssql://db/#temp_int' (FORMAT 'bcp', CREATE_TABLE false);\n\nquery I\nSELECT COUNT(*) FROM mssql_scan('db', 'SELECT * FROM #temp_int');\n----\n10\n\n# The original BIGINT source is narrowing and must still be rejected.\nstatement error\nCOPY local_test TO 'mssql://db/#temp_int' (FORMAT 'bcp', CREATE_TABLE false);\n----\ntype mismatch\n\nstatement ok\nROLLBACK;""",
        label="copy_existing_temp narrowing assertion",
    )
    labels.append(label)

    text, label = replace_exact(
        text,
        """# Copy to existing temp table with different types - should use target column metadata\nstatement ok\nCOPY local_multi TO 'mssql://db/#temp_multi' (FORMAT 'bcp', CREATE_TABLE false);""",
        """# Cast the BIGINT id to INTEGER; the other target types are compatible.\nstatement ok\nCREATE TABLE local_multi_int AS SELECT id::INTEGER AS id, name, value FROM local_multi;\n\nstatement ok\nCOPY local_multi_int TO 'mssql://db/#temp_multi' (FORMAT 'bcp', CREATE_TABLE false);""",
        label="copy_existing_temp multi-column INT source",
    )
    labels.append(label)

    write_change(path, before, text, labels, report)


def patch_connection_leak(path: Path, report: list[dict[str, Any]]) -> None:
    before = read_text(path)
    text = before
    labels: list[str] = []

    text, label = replace_exact(
        text,
        "pool_size, idle_connections, active_connections, total_connections_created",
        "total_connections, idle_connections, active_connections, connections_created",
        label="copy_connection_leak four-column pool schema",
        expected=3,
    )
    labels.append(label)

    text, label = replace_exact(
        text,
        "idle_connections, active_connections, total_connections_created",
        "idle_connections, active_connections, connections_created",
        label="copy_connection_leak three-column pool schema",
        expected=4,
    )
    labels.append(label)

    text, label = replace_exact(
        text,
        "10\t1\t0\t1",
        "1\t1\t0\t1",
        label="copy_connection_leak live connection count",
        expected=4,
    )
    labels.append(label)

    text, label = replace_exact(
        text,
        """COPY test_data TO 'nonexistent_catalog.dbo.test' (FORMAT 'bcp');\n----\nnot found""",
        """COPY test_data TO 'nonexistent_catalog.dbo.test' (FORMAT 'bcp');\n----\ndoes not exist""",
        label="copy_connection_leak current catalog error",
    )
    labels.append(label)

    write_change(path, before, text, labels, report)


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: prepare-mssql-release-tests.py <upstream-root> <report-json>")

    upstream_root = Path(sys.argv[1]).resolve()
    report_path = Path(sys.argv[2]).resolve()
    test_root = upstream_root / "test" / "sql"
    if not test_root.is_dir():
        raise SystemExit(f"MSSQL SQLLogicTest directory is missing: {test_root}")

    changes: list[dict[str, Any]] = []
    scalar_call_count = patch_scalar_calls(test_root, changes)
    patch_copy_type_mismatch(test_root / "copy" / "copy_type_mismatch.test", changes)
    patch_copy_existing_temp(test_root / "copy" / "copy_existing_temp.test", changes)
    patch_connection_leak(test_root / "copy" / "copy_connection_leak.test", changes)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "contract": PATCH_CONTRACT,
                "upstream_root": upstream_root.as_posix(),
                "scalar_call_replacements": scalar_call_count,
                "files_changed": len(changes),
                "files": changes,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"Applied {PATCH_CONTRACT}: {scalar_call_count} scalar CALL replacement(s), "
        f"{len(changes)} changed file(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
