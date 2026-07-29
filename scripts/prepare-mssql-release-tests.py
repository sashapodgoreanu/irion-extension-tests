#!/usr/bin/env python3
"""Validate the pinned MSSQL v0.2.2 SQLLogicTest checkout.

MSSQL v0.2.2 already contains the deterministic SQLLogicTest fixes that this
repository previously applied to v0.2.1. The QA preparation step now verifies
those upstream contracts instead of rewriting the checkout. This keeps the
runner fail-closed if a future release changes the expected test semantics.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

PATCH_CONTRACT = "mssql-v0.2.2-upstream-sqllogictest-contract-v1"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_text(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"Expected upstream test file is missing: {path}")
    return path.read_text(encoding="utf-8")


def require_text(text: str, expected: str, *, label: str) -> None:
    if expected not in text:
        raise SystemExit(f"MSSQL v0.2.2 contract mismatch: missing {label}")


def validate_scalar_exec_syntax(test_root: Path) -> int:
    call_pattern = re.compile(r"(?im)^[ \t]*CALL[ \t]+mssql_exec\(")
    select_pattern = re.compile(r"(?im)^[ \t]*SELECT[ \t]+mssql_exec\(")
    call_count = 0
    select_count = 0

    for path in sorted(test_root.rglob("*.test*")):
        text = read_text(path)
        call_count += len(call_pattern.findall(text))
        select_count += len(select_pattern.findall(text))

    if call_count:
        raise SystemExit(
            "MSSQL v0.2.2 contract mismatch: "
            f"found {call_count} obsolete CALL mssql_exec statement(s)"
        )
    if select_count == 0:
        raise SystemExit(
            "MSSQL v0.2.2 contract mismatch: no SELECT mssql_exec statements were found"
        )
    return select_count


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: prepare-mssql-release-tests.py <upstream-root> <report-json>"
        )

    upstream_root = Path(sys.argv[1]).resolve()
    report_path = Path(sys.argv[2]).resolve()
    test_root = upstream_root / "test" / "sql"
    if not test_root.is_dir():
        raise SystemExit(f"MSSQL SQLLogicTest directory is missing: {test_root}")

    copy_type_mismatch = read_text(
        test_root / "copy" / "copy_type_mismatch.test"
    )
    copy_existing_temp = read_text(
        test_root / "copy" / "copy_existing_temp.test"
    )
    copy_connection_leak = read_text(
        test_root / "copy" / "copy_connection_leak.test"
    )

    select_exec_count = validate_scalar_exec_syntax(test_root)

    validations: list[dict[str, Any]] = []

    contracts = [
        (
            test_root / "copy" / "copy_type_mismatch.test",
            copy_type_mismatch,
            "COPY (SELECT id::INTEGER AS id FROM bigint_source)",
            "explicit BIGINT-to-INT cast",
        ),
        (
            test_root / "copy" / "copy_existing_temp.test",
            copy_existing_temp,
            "CREATE TABLE local_test_int AS SELECT id::INTEGER AS id FROM local_test;",
            "temporary-table integer source",
        ),
        (
            test_root / "copy" / "copy_connection_leak.test",
            copy_connection_leak,
            "SELECT total_connections, idle_connections, active_connections, connections_created",
            "current pool statistics schema",
        ),
        (
            test_root / "copy" / "copy_connection_leak.test",
            copy_connection_leak,
            "does not exist",
            "current missing-catalog error",
        ),
    ]

    for path, text, expected, label in contracts:
        require_text(text, expected, label=label)
        validations.append(
            {
                "path": path.relative_to(upstream_root).as_posix(),
                "sha256": sha256_text(text),
                "contract": label,
            }
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "contract": PATCH_CONTRACT,
                "upstream_root": upstream_root.as_posix(),
                "select_mssql_exec_statements": select_exec_count,
                "files_changed": 0,
                "validations": validations,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"Validated {PATCH_CONTRACT}: {select_exec_count} SELECT mssql_exec "
        f"statement(s), {len(validations)} contract checks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
