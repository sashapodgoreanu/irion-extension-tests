#!/usr/bin/env python3
"""Adjust the pinned Azure SQLLogicTest for nondeterministic cached GET counts.

The Azure extension's HTTP statistics profile may report zero or one GET when
the same Parquet file is read, depending on cache state. Keep all other
request-count assertions intact. Apply only to the two private-container
EXPLAIN ANALYZE expectations; never change the public-blob assertion.
"""

from __future__ import annotations

import sys
from pathlib import Path

OLD = r"GET\: 0"
UPDATED = r"GET\: [01]"
PRIVATE_HEAD = r"\#HEAD\: 4"
REQUIRED = (r"PUT\: 0", r"\#POST\: 0")


def adapt(upstream_root: Path) -> int:
    path = upstream_root / "test" / "sql" / "azure.test"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    matches = 0
    updated = 0

    for index, line in enumerate(lines):
        if (
            line.startswith("analyzed_plan\t<REGEX>:")
            and PRIVATE_HEAD in line
            and all(item in line for item in REQUIRED)
        ):
            if OLD in line:
                lines[index] = line.replace(OLD, UPDATED, 1)
                matches += 1
                updated += 1
            elif UPDATED in line:
                matches += 1

    if matches != 2:
        raise ValueError(
            f"Azure private HTTP statistics expectation changed: "
            f"found {matches} expected lines in {path}, required 2"
        )

    if updated:
        path.write_text("".join(lines), encoding="utf-8")
    print(f"Azure test expectation adjusted: {updated} lines (2 checked)", flush=True)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: prepare-azure-tests.py UPSTREAM_ROOT")
    try:
        raise SystemExit(adapt(Path(sys.argv[1])))
    except (OSError, ValueError) as exc:
        print(f"Azure test preparation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
