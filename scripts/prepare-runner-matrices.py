#!/usr/bin/env python3
"""Resolve the same declarative QA batteries for every configured OS runner."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from qa import ConfigError, load_config, resolve_config  # noqa: E402
from qa.plan import ExecutionPlan, ExecutionRuntime  # noqa: E402


class RunnerConfigError(ValueError):
    pass


def required_string(mapping: dict[str, Any], key: str, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RunnerConfigError(f"{path}.{key} must be a non-empty string")
    return value.strip()


def load_runners(path: Path) -> dict[str, dict[str, Any]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RunnerConfigError("runner configuration must be a mapping")
    if raw.get("schemaVersion") != 1:
        raise RunnerConfigError("runner configuration schemaVersion must be 1")
    runners = raw.get("runners")
    if not isinstance(runners, dict) or not runners:
        raise RunnerConfigError("runners must contain at least one runner")

    normalized: dict[str, dict[str, Any]] = {}
    for name, value in runners.items():
        if not isinstance(name, str) or not name:
            raise RunnerConfigError("runner names must be non-empty strings")
        if not isinstance(value, dict):
            raise RunnerConfigError(f"runners.{name} must be a mapping")
        enabled = value.get("isEnabled")
        if not isinstance(enabled, bool):
            raise RunnerConfigError(f"runners.{name}.isEnabled must be a boolean")
        operating_system = required_string(value, "operatingSystem", f"runners.{name}")
        architecture = required_string(value, "architecture", f"runners.{name}")
        github_runner = required_string(value, "githubRunner", f"runners.{name}")
        normalized[name] = {
            "isEnabled": enabled,
            "operatingSystem": operating_system,
            "architecture": architecture,
            "githubRunner": github_runner,
        }
    return normalized


def runtime_for(plan: ExecutionPlan, runner: dict[str, Any]) -> ExecutionRuntime:
    return ExecutionRuntime(
        duckdb_version=plan.runtime.duckdb_version,
        ci_tools_version=plan.runtime.ci_tools_version,
        operating_system=runner["operatingSystem"],
        architecture=runner["architecture"],
        github_runner=runner["githubRunner"],
    )


def runner_plan(plan: ExecutionPlan, runner: dict[str, Any]) -> ExecutionPlan:
    return ExecutionPlan(
        runtime=runtime_for(plan, runner),
        cases=plan.cases,
        schema_version=plan.schema_version,
    )


def resolve_runner_matrices(
    extensions_config: Path,
    runners_config: Path,
) -> tuple[ExecutionPlan, dict[str, dict[str, Any]]]:
    plan = resolve_config(load_config(extensions_config))
    runners = load_runners(runners_config)
    resolved: dict[str, dict[str, Any]] = {}

    for name, runner in runners.items():
        resolved_plan = runner_plan(plan, runner)
        include = (
            resolved_plan.matrix()["include"]
            if runner["isEnabled"]
            else []
        )
        resolved[name] = {
            **runner,
            "matrix": {"include": include},
            "runtime": resolved_plan.runtime.payload(),
            "executionPlanSha256": resolved_plan.sha256(),
        }

    return plan, resolved


def runner_plan_path(base: Path, runner_name: str) -> Path:
    return base.with_name(f"{base.stem}-{runner_name}{base.suffix}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("extensions_config", type=Path)
    parser.add_argument("runners_config", type=Path)
    parser.add_argument("--plan-output", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        plan, runners = resolve_runner_matrices(
            args.extensions_config,
            args.runners_config,
        )
        if args.plan_output is not None:
            # Keep the original path for backwards compatibility, and emit a
            # runtime-correct plan for each enabled matrix used by aggregation.
            plan.write_json(args.plan_output)
            for name, runner in runners.items():
                runner_plan(plan, runner).write_json(
                    runner_plan_path(args.plan_output, name)
                )
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps({"runners": runners}, indent=2) + "\n",
                encoding="utf-8",
            )

        print(f"duckdb_version={plan.runtime.duckdb_version}")
        print(f"ci_tools_version={plan.runtime.ci_tools_version}")
        print(f"enabled_batteries={','.join(case.name for case in plan.cases)}")
        print(f"execution_plan_sha256={plan.sha256()}")
        print(
            "enabled_runners="
            + ",".join(name for name, item in runners.items() if item["isEnabled"])
        )
        for name, item in runners.items():
            prefix = name.replace("-", "_")
            print(f"{prefix}_enabled={str(item['isEnabled']).lower()}")
            print(
                f"{prefix}_matrix="
                + json.dumps(item["matrix"], separators=(",", ":"))
            )
            print(f"{prefix}_operating_system={item['operatingSystem']}")
            print(f"{prefix}_architecture={item['architecture']}")
            print(f"{prefix}_github_runner={item['githubRunner']}")
            print(f"{prefix}_execution_plan_sha256={item['executionPlanSha256']}")
        return 0
    except (OSError, yaml.YAMLError, ConfigError, RunnerConfigError) as exc:
        print(f"Invalid QA runner configuration: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
