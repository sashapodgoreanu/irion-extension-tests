#!/usr/bin/env python3
"""Adapt DuckLake SQLLogicTests for one reused PostgreSQL metadata catalog.

The upstream tests use `${DUCKLAKE_CONNECTION}` so the same suite can run
against SQLite and PostgreSQL. In the PostgreSQL profile every test file uses
the same metadata database (`ducklakedb`) but a different temporary DATA_PATH.
DuckLake v1.5.5 correctly rejects that change unless OVERRIDE_DATA_PATH is
explicit. Add the option only to variable-backed test attachments, leaving
literal-path tests (including the negative different-path contract) unchanged.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

CONTRACT = "ducklake-v1.5.5-postgres-data-path-isolation-v1"
ATTACH_MARKER = "ATTACH 'ducklake:${DUCKLAKE_CONNECTION}'"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def patch_line(line: str, path: Path, line_number: int) -> tuple[str, bool]:
    if ATTACH_MARKER not in line or "DATA_PATH" not in line:
        return line, False
    if "OVERRIDE_DATA_PATH" in line:
        return line, False

    closing = line.rfind(")")
    if closing < 0:
        raise SystemExit(
            f"DuckLake patch contract mismatch: multiline or malformed ATTACH "
            f"at {path}:{line_number}"
        )
    return line[:closing] + ", OVERRIDE_DATA_PATH TRUE" + line[closing:], True


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: prepare-ducklake-postgres-tests.py <upstream-root> <report-json>"
        )

    upstream_root = Path(sys.argv[1]).resolve()
    report_path = Path(sys.argv[2]).resolve()
    test_root = upstream_root / "test" / "sql"
    if not test_root.is_dir():
        raise SystemExit(f"DuckLake SQLLogicTest directory is missing: {test_root}")

    patched_files: list[dict[str, object]] = []
    matched_attachments = 0
    patched_attachments = 0

    for path in sorted(test_root.rglob("*.test*")):
        before = path.read_text(encoding="utf-8")
        lines = before.splitlines(keepends=True)
        changed = False
        file_matches = 0
        file_patches = 0

        for index, line in enumerate(lines):
            if ATTACH_MARKER in line and "DATA_PATH" in line:
                matched_attachments += 1
                file_matches += 1
            updated, was_patched = patch_line(line, path, index + 1)
            if was_patched:
                lines[index] = updated
                patched_attachments += 1
                file_patches += 1
                changed = True

        if not changed:
            continue

        after = "".join(lines)
        path.write_text(after, encoding="utf-8")
        patched_files.append(
            {
                "path": path.relative_to(upstream_root).as_posix(),
                "matches": file_matches,
                "patches": file_patches,
                "before_sha256": digest(before),
                "after_sha256": digest(after),
            }
        )

    if matched_attachments == 0:
        raise SystemExit(
            "DuckLake patch contract mismatch: no variable-backed DATA_PATH attachments found"
        )

    remaining = []
    for path in sorted(test_root.rglob("*.test*")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if (
                ATTACH_MARKER in line
                and "DATA_PATH" in line
                and "OVERRIDE_DATA_PATH" not in line
            ):
                remaining.append(f"{path}:{line_number}")
    if remaining:
        raise SystemExit(
            "DuckLake patch contract mismatch: unpatched attachments remain: "
            + ", ".join(remaining[:10])
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "contract": CONTRACT,
                "upstream_root": upstream_root.as_posix(),
                "matched_attachments": matched_attachments,
                "patched_attachments": patched_attachments,
                "files_changed": len(patched_files),
                "files": patched_files,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"Applied {CONTRACT}: {patched_attachments} attachment(s) in "
        f"{len(patched_files)} file(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
