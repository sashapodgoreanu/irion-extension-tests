#!/usr/bin/env python3
"""Fail when SQLLogicTest skipped a configured extension requirement."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REQUIRE_LINE = re.compile(r"^require\s+([^:]+):\s+([1-9][0-9]*)$")


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} UNITTEST_LOG EXTENSIONS_JSON", file=sys.stderr)
        return 2

    selected = {
        item["name"]
        for item in json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    }
    skipped: list[tuple[str, int]] = []
    for line in Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace").splitlines():
        match = REQUIRE_LINE.fullmatch(line.strip())
        if match and match.group(1) in selected:
            skipped.append((match.group(1), int(match.group(2))))

    if skipped:
        for name, count in skipped:
            print(f"Required configured extension was skipped: {name} ({count})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
