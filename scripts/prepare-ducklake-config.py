#!/usr/bin/env python3
"""Adapt a pinned DuckLake test config for dynamically installed extensions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REQUIRED_EXTENSIONS = (
    "core_functions",
    "parquet",
    "json",
    "tpch",
    "tpcds",
    "icu",
    "httpfs",
    "ducklake",
    "mssql",
    "postgres_scanner",
    "sqlite_scanner",
)

ADDITIONAL_SKIP_REASON = "Test specific to the PostgreSQL catalog suite"


def main() -> int:
    if len(sys.argv) < 3:
        print(
            f"usage: {sys.argv[0]} SOURCE_CONFIG DEST_CONFIG [SKIP_TEST ...]",
            file=sys.stderr,
        )
        return 2

    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    additional_skip_paths = sys.argv[3:]
    config = json.loads(source.read_text(encoding="utf-8"))

    config["autoloading"] = "all"
    config["summarize_failures"] = True

    extensions = list(config.get("statically_loaded_extensions", []))
    for extension in REQUIRED_EXTENSIONS:
        if extension not in extensions:
            extensions.append(extension)
    config["statically_loaded_extensions"] = extensions

    if additional_skip_paths:
        skip_tests = list(config.get("skip_tests", []))
        skip_tests.append(
            {
                "reason": ADDITIONAL_SKIP_REASON,
                "paths": additional_skip_paths,
            }
        )
        config["skip_tests"] = skip_tests

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
