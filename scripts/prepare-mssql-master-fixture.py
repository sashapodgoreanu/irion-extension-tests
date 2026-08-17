#!/usr/bin/env python3
"""Validate the master catalog fixture shipped with the pinned MSSQL release.

The QA preparation step validates the upstream fixture without rewriting it and
fails closed if a future release changes the required catalog contract.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

CONTRACT = "mssql-release-master-catalog-fixture-v1"

REQUIRED_FRAGMENTS = (
    "IF OBJECT_ID('master.dbo.test', 'U') IS NOT NULL DROP TABLE master.dbo.test;",
    "CREATE TABLE master.dbo.test (",
    "INSERT INTO master.dbo.test (id, name) VALUES (1, 'A'), (2, 'B'), (3, 'C');",
    "PRINT 'master.dbo.test created';",
)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: prepare-mssql-master-fixture.py <upstream-root> <report-json>"
        )

    upstream_root = Path(sys.argv[1]).resolve()
    report_path = Path(sys.argv[2]).resolve()
    seed_path = upstream_root / "docker" / "init" / "init.sql"
    if not seed_path.is_file():
        raise SystemExit(f"Pinned MSSQL seed script is missing: {seed_path}")

    content = seed_path.read_text(encoding="utf-8")
    missing = [fragment for fragment in REQUIRED_FRAGMENTS if fragment not in content]
    if missing:
        raise SystemExit(
            "MSSQL release fixture contract mismatch; missing: " + ", ".join(missing)
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "contract": CONTRACT,
                "path": seed_path.as_posix(),
                "sha256": digest(content),
                "files_changed": 0,
                "validated_fragments": len(REQUIRED_FRAGMENTS),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"Validated {CONTRACT}: {len(REQUIRED_FRAGMENTS)} fixture contract checks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
