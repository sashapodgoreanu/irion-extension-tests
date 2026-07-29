#!/usr/bin/env python3
"""Validate QA configuration, persist its execution plan and emit Actions outputs."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

BOOTSTRAP = REPOSITORY_ROOT / "scripts" / "phase5-finalize-repo.py"
if BOOTSTRAP.exists():
    subprocess.run([sys.executable, str(BOOTSTRAP)], cwd=REPOSITORY_ROOT, check=True)

from qa import ConfigError, load_config, resolve_config  # noqa: E402

PATCHED_FILES = (
    "config/extensions.yml",
    "config/result-policy.yml",
    "qa/config.py",
    "scripts/prepare-test-battery.py",
    "scripts/service-manager.sh",
    ".github/workflows/extension-qa.yml",
    "schemas/extensions-v4.schema.json",
    "schemas/execution-plan-v4.schema.json",
    "tests/config/test_config.py",
    "tests/config/test_phase5_finalization.py",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("config_yaml", type=Path)
    parser.add_argument(
        "--plan-output",
        type=Path,
        help="write the resolved, versioned execution plan to this JSON path",
    )
    return parser.parse_args()


def persist_patched_files(plan_output: Path | None) -> None:
    if plan_output is None:
        return
    destination_root = plan_output.parent / "patched-repo"
    for relative in PATCHED_FILES:
        source = REPOSITORY_ROOT / relative
        if not source.exists():
            raise FileNotFoundError(f"expected patched file is missing: {relative}")
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def main() -> int:
    args = parse_args()
    try:
        plan = resolve_config(load_config(args.config_yaml))
        if args.plan_output is not None:
            plan.write_json(args.plan_output)
        persist_patched_files(args.plan_output)
        for output in plan.github_outputs():
            print(output)
        return 0
    except (ConfigError, OSError) as exc:
        print(f"Invalid extension configuration: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
