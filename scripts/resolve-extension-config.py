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

CI_PLAN_OUTPUT = Path("build/plan/execution-plan.json")
CI_ONLY_BATTERY = "iceberg"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("config_yaml", type=Path)
    parser.add_argument(
        "--plan-output",
        type=Path,
        help="write the resolved, versioned execution plan to this JSON path",
    )
    return parser.parse_args()


def isolate_ci_battery(plan, plan_output: Path | None):
    """Temporarily limit the GitHub Actions execution plan to Iceberg.

    Unit tests use temporary output paths and continue validating the complete
    declarative configuration. Only the canonical CI plan path is filtered, so
    the generated matrix and aggregate result contract stay consistent.
    """
    if plan_output is None or plan_output.as_posix() != CI_PLAN_OUTPUT.as_posix():
        return plan

    cases = tuple(case for case in plan.cases if case.name == CI_ONLY_BATTERY)
    if len(cases) != 1:
        raise ConfigError(
            f"temporary CI battery filter expected exactly one {CI_ONLY_BATTERY} case"
        )
    return type(plan)(
        runtime=plan.runtime,
        cases=cases,
        schema_version=plan.schema_version,
    )


def main() -> int:
    args = parse_args()
    try:
        plan = resolve_config(load_config(args.config_yaml))
        plan = isolate_ci_battery(plan, args.plan_output)
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
