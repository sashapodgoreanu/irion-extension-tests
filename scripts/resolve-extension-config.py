#!/usr/bin/env python3
"""Validate config/extensions.yml and emit the GitHub Actions matrix."""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from qa import ConfigError, load_config, resolve_config  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} CONFIG_YAML", file=sys.stderr)
        return 2
    try:
        resolved = resolve_config(load_config(Path(sys.argv[1])))
        for output in resolved.github_outputs():
            print(output)
        return 0
    except ConfigError as exc:
        print(f"Invalid extension configuration: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
