#!/usr/bin/env python3
"""Validate QA configuration, persist its execution plan and emit Actions outputs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from qa import ConfigError, load_config, resolve_config  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("config_yaml", type=Path)
    parser.add_argument(
        "--plan-output",
        type=Path,
        help="write the resolved, versioned execution plan to this JSON path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        plan = resolve_config(load_config(args.config_yaml))
        if args.plan_output is not None:
            plan.write_json(args.plan_output)
        for output in plan.github_outputs():
            print(output)
        return 0
    except ConfigError as exc:
        print(f"Invalid extension configuration: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
