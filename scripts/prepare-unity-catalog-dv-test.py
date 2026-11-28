#!/usr/bin/env python3
"""Load the signed dynamic Unity Catalog binary before testing its DV helper.

The pinned upstream Unity Catalog integration runner links the extension into
its own unittest binary. Our compatibility runner intentionally uses DuckDB's
standalone unittest and installs the signed extension dynamically. The upstream
dv_decode.test has 'require unity_catalog' but never explicitly LOADs it, so
its custom table function is absent when the first query is bound.

Only insert an explicit LOAD. Never alter, remove, skip, or accept failures in
the upstream assertions. Fail if the pinned fixture changes unexpectedly.
"""

from __future__ import annotations

import argparse
from pathlib import Path


class AdaptationError(RuntimeError):
    pass


REQUIRE = "require unity_catalog\n"
LAST_ENV = "require-env DV_TRAILING_SIZE\n"
FUNCTION = "uc_read_deletion_vector("
LOAD_BLOCK = (
    "\n# QA dynamic-loading compatibility: signed Unity Catalog is not statically linked\n"
    "# into the shared DuckDB unittest binary. LOAD exposes its helper function.\n"
    "statement ok\n"
    "LOAD unity_catalog;\n"
)


def adapt(path: Path) -> bool:
    content = path.read_text(encoding="utf-8")
    if content.count(REQUIRE) != 1:
        raise AdaptationError("expected exactly one 'require unity_catalog' directive")
    if content.count(LAST_ENV) != 1:
        raise AdaptationError("expected exactly one DV_TRAILING_SIZE requirement")
    if FUNCTION not in content:
        raise AdaptationError("upstream DV test no longer invokes uc_read_deletion_vector")
    if LOAD_BLOCK in content:
        return False
    if "LOAD unity_catalog;" in content:
        raise AdaptationError("upstream DV test already loads Unity Catalog differently")

    offset = content.index(LAST_ENV) + len(LAST_ENV)
    first_query = content.find("query I")
    if first_query < 0 or offset >= first_query:
        raise AdaptationError("DV environment requirements no longer precede SQL queries")
    path.write_text(content[:offset] + LOAD_BLOCK + content[offset:], encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream_root", type=Path)
    args = parser.parse_args()
    path = args.upstream_root / "test/functions/dv_decode.test"
    changed = adapt(path)
    print(f"Unity Catalog DV dynamic load: {'inserted' if changed else 'already present'} ({path})")


if __name__ == "__main__":
    main()
