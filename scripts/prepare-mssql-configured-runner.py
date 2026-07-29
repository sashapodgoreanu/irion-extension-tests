#!/usr/bin/env python3
"""Create an MSSQL runtime runner controlled by declarative QA services."""

from __future__ import annotations

import sys
from pathlib import Path


class PatchError(ValueError):
    pass


SQLSERVER_REPLACEMENT = [
    'SQLSERVER_ID="${SQLSERVER_ID:?SQL Server service container id is required}"',
    'if ! docker exec "${SQLSERVER_ID}" /opt/mssql-tools18/bin/sqlcmd \\',
    '    -S localhost -U "${MSSQL_TEST_USER}" -P "${MSSQL_TEST_PASS}" -C \\',
    "    -Q 'SELECT 1' >/dev/null 2>&1; then",
    '  echo "SQL Server service is not ready" >&2',
    '  exit 1',
    'fi',
]


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
        cleanup_blocks = 0
        lifecycle_blocks = 0
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
            if line == "cleanup() {":
                cleanup_blocks += 1
                while index < len(lines) and lines[index] != "trap cleanup EXIT":
                    index += 1
                if index >= len(lines):
                    raise PatchError("MSSQL cleanup trap terminator was not found")
                index += 1
                continue
            if line == 'docker compose -f "${COMPOSE_FILE}" up -d sqlserver':
                lifecycle_blocks += 1
                saw_failure = False
                while index < len(lines):
                    current = lines[index]
                    if 'echo "SQL Server did not become ready"' in current:
                        saw_failure = True
                    index += 1
                    if saw_failure and current == "fi":
                        break
                if not saw_failure:
                    raise PatchError("SQL Server readiness block terminator was not found")
                output.extend(SQLSERVER_REPLACEMENT)
                continue
            output.append(line)
            index += 1

        if version_replacements != 1:
            raise PatchError(
                f"expected one DuckDB version assignment, found {version_replacements}"
            )
        if skip_blocks != 1:
            raise PatchError(f"expected one legacy skip_tests block, found {skip_blocks}")
        if cleanup_blocks != 1:
            raise PatchError(f"expected one SQL Server cleanup block, found {cleanup_blocks}")
        if lifecycle_blocks != 1:
            raise PatchError(
                f"expected one SQL Server lifecycle block, found {lifecycle_blocks}"
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("\n".join(output) + "\n", encoding="utf-8")
        destination.chmod(0o755)
        return 0
    except (OSError, PatchError) as exc:
        print(f"Unable to prepare configured MSSQL runner: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
