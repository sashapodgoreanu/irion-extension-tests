#!/usr/bin/env python3
"""Verify Iceberg metadata functions excluded from the dynamic-runner test files."""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} DUCKDB_BIN UPSTREAM_ROOT", file=sys.stderr)
        return 2

    duckdb = Path(sys.argv[1]).resolve()
    upstream = Path(sys.argv[2]).resolve()
    table = upstream / "data/persistent/hive_partitioned_table"
    if not duckdb.is_file():
        print(f"DuckDB executable is missing: {duckdb}", file=sys.stderr)
        return 1
    if not table.is_dir():
        print(f"Iceberg metadata fixture is missing: {table}", file=sys.stderr)
        return 1

    escaped_table = str(table).replace("'", "''")
    sql = f"""
LOAD iceberg;
SELECT 'partition_stats', count(*)
FROM ICEBERG_PARTITION_STATS('{escaped_table}', ALLOW_MOVED_PATHS=TRUE);
SELECT 'column_stats', count(*)
FROM ICEBERG_COLUMN_STATS('{escaped_table}', ALLOW_MOVED_PATHS=TRUE);
"""
    process = subprocess.run(
        [str(duckdb), "-csv", "-noheader", "-c", sql],
        check=False,
        text=True,
        capture_output=True,
    )
    if process.stdout:
        print(process.stdout, end="")
    if process.stderr:
        print(process.stderr, file=sys.stderr, end="")
    if process.returncode != 0:
        return process.returncode

    rows = list(csv.reader(process.stdout.splitlines()))
    actual = {row[0]: int(row[1]) for row in rows if len(row) == 2}
    expected = {"partition_stats": 3, "column_stats": 18}
    if actual != expected:
        print(
            f"Unexpected Iceberg metadata counts: actual={actual}, expected={expected}",
            file=sys.stderr,
        )
        return 1
    print("Iceberg metadata smoke passed: partition_stats=3, column_stats=18")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
