#!/usr/bin/env python3
"""Create a runtime MSSQL base runner controlled by config/extensions.yml."""

from __future__ import annotations

import sys
from pathlib import Path


class PatchError(ValueError):
    pass


def main() -> int:
    if len(sys.argv) != 4:
        print(f"usage: {sys.argv[0]} SOURCE DEST DUCKDB_VERSION", file=sys.stderr)
        return 2

    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    duckdb_version = sys.argv[3]
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
        version_replacements = 0
        skip_blocks = 0
        output: list[str] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if line.startswith('DUCKDB_VERSION_DIRECTORY="'):
                output.append(f'DUCKDB_VERSION_DIRECTORY="${{DUCKDB_VERSION:-{duckdb_version}}}"')
                version_replacements += 1
                index += 1
                continue
            if line == '    "skip_tests": [':
                skip_blocks += 1
                depth = 0
                while index < len(lines):
                    current = lines[index]
                    depth += current.count("[")
                    depth -= current.count("]")
                    index += 1
                    if depth == 0:
                        break
                continue
            output.append(line)
            index += 1

        if version_replacements != 1:
            raise PatchError(
                f"expected one DuckDB version assignment, found {version_replacements}"
            )
        if skip_blocks != 1:
            raise PatchError(f"expected one legacy skip_tests block, found {skip_blocks}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("\n".join(output) + "\n", encoding="utf-8")
        destination.chmod(0o755)
        return 0
    except (OSError, PatchError) as exc:
        print(f"Unable to prepare configured MSSQL runner: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
