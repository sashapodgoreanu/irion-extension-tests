#!/usr/bin/env python3
"""Add the catalog_discovery fixture missing from MSSQL release v0.2.1.

The v0.2.1 SQLLogicTest attaches MSSQL_TEST_DSN, whose default database is
master, and expects master.dbo.test. The release seed script only creates the
same table in TestDB. Upstream fixed this when it enabled the SQLLogicTest suite
in issue #192. This helper applies that test-fixture-only correction to the
temporary pinned checkout and refuses to patch unexpected content.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

CONTRACT = "mssql-v0.2.1-master-catalog-fixture-v1"

OLD_BLOCK = """IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = 'TestDB')
BEGIN
    CREATE DATABASE TestDB;
    PRINT 'TestDB created';
END
GO

USE TestDB;
GO
"""

NEW_BLOCK = """IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = 'TestDB')
BEGIN
    CREATE DATABASE TestDB;
    PRINT 'TestDB created';
END
GO

-- Test-side compatibility fixture from upstream issue #192.
-- catalog_discovery.test attaches Database=master and expects dbo.test there.
IF OBJECT_ID('master.dbo.test', 'U') IS NOT NULL DROP TABLE master.dbo.test;
GO

CREATE TABLE master.dbo.test (
    id INT PRIMARY KEY,
    name NVARCHAR(50)
);
GO

INSERT INTO master.dbo.test (id, name) VALUES
    (1, 'A'), (2, 'B'), (3, 'C');
GO

PRINT 'master.dbo.test created';
GO

USE TestDB;
GO
"""


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

    before = seed_path.read_text(encoding="utf-8")
    count = before.count(OLD_BLOCK)
    if count != 1:
        raise SystemExit(
            f"Fixture patch contract mismatch: expected one v0.2.1 seed block, found {count}"
        )
    if "master.dbo.test created" in before:
        raise SystemExit("Fixture patch contract mismatch: master.dbo.test is already present")

    after = before.replace(OLD_BLOCK, NEW_BLOCK, 1)
    seed_path.write_text(after, encoding="utf-8")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "contract": CONTRACT,
                "path": seed_path.as_posix(),
                "before_sha256": digest(before),
                "after_sha256": digest(after),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Applied {CONTRACT} to {seed_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
