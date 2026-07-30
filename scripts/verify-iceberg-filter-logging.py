#!/usr/bin/env python3
"""Verify the detailed Iceberg partition-pruning log emitted by the pinned binary."""

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
    metadata = (
        upstream
        / "data/persistent/large_partitioned_table/metadata/v2.metadata.json"
    )
    if not duckdb.is_file():
        print(f"DuckDB executable is missing: {duckdb}", file=sys.stderr)
        return 1
    if not metadata.is_file():
        print(f"Iceberg partition fixture is missing: {metadata}", file=sys.stderr)
        return 1

    escaped_metadata = str(metadata).replace("'", "''")
    sql = f"""
LOAD iceberg;
SET TimeZone='UTC';
CALL enable_logging(level='debug');
SELECT count(*)
FROM (
    SELECT *
    FROM ICEBERG_SCAN('{escaped_metadata}')
    WHERE joined >= '1984-12-01 00:00:00+01'::TIMESTAMP
    ORDER BY id DESC
    LIMIT 10
);
SELECT message
FROM duckdb_logs()
WHERE type = 'Iceberg'
  AND message LIKE 'Iceberg Filter Pushdown, skipped %'
GROUP BY message
ORDER BY message;
"""
    process = subprocess.run(
        [str(duckdb), "-csv", "-noheader", "-c", sql],
        cwd=upstream,
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
    if ["10"] not in rows:
        print(
            "Filtered Iceberg query did not return the expected ten-row limit",
            file=sys.stderr,
        )
        return 1

    messages = [
        row[0]
        for row in rows
        if len(row) == 1 and row[0].startswith("Iceberg Filter Pushdown, skipped ")
    ]
    if len(messages) != 8:
        print(
            f"Unexpected Iceberg partition-pruning log count: {len(messages)}; expected 8",
            file=sys.stderr,
        )
        return 1

    required_fragments = (
        "partition column 'joined' has raw value",
        "with transform 'month'",
        "does not match filter: joined>=",
    )
    for message in messages:
        missing = [fragment for fragment in required_fragments if fragment not in message]
        if missing:
            print(
                f"Iceberg pruning log is missing {missing}: {message}",
                file=sys.stderr,
            )
            return 1

    print("Iceberg filter logging smoke passed: 8 detailed partition-pruning messages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
