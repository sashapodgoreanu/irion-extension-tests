#!/usr/bin/env python3
"""Validate that every resolved extension is installed and loaded."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} EXTENSIONS_CSV EXTENSIONS_JSON", file=sys.stderr)
        return 2

    rows = list(csv.DictReader(Path(sys.argv[1]).open(encoding="utf-8")))
    expected = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    by_name = {row.get("extension_name", ""): row for row in rows}

    errors: list[str] = []
    for extension in expected:
        name = extension["name"]
        row = by_name.get(name)
        if not row:
            errors.append(f"{name} is missing from duckdb_extensions()")
            continue
        if row.get("installed", "").lower() != "true":
            errors.append(f"{name} is not installed")
        if row.get("loaded", "").lower() != "true":
            errors.append(f"{name} is not loaded")
        install_from = extension.get("installFrom")
        if install_from and row.get("installed_from", "").lower() != install_from.lower():
            errors.append(
                f"{name} was installed from {row.get('installed_from') or '<empty>'}, "
                f"expected {install_from}"
            )

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Resolved extension set installed and loaded successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
