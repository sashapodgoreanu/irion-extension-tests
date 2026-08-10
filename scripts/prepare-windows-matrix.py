#!/usr/bin/env python3
"""Resolve the supplemental native-Windows SQLLogicTest matrix."""

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
from qa.plan import ExecutionRuntime  # noqa: E402


class WindowsConfigError(ValueError):
    pass


def _required_string(mapping: dict[str, Any], key: str, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WindowsConfigError(f"{path}.{key} must be a non-empty string")
    return value.strip()


def _load_windows_config(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise WindowsConfigError("Windows configuration must be a mapping")
    if raw.get("schemaVersion") != 1:
        raise WindowsConfigError("Windows configuration schemaVersion must be 1")
    return raw


def resolve_windows_matrix(main_config: Path, windows_config: Path) -> tuple[dict[str, Any], ExecutionRuntime]:
    plan = resolve_config(load_config(main_config))
    raw = _load_windows_config(windows_config)

    runtime_raw = raw.get("runtime")
    if not isinstance(runtime_raw, dict):
        raise WindowsConfigError("runtime must be a mapping")
    runtime = ExecutionRuntime(
        duckdb_version=plan.runtime.duckdb_version,
        ci_tools_version=plan.runtime.ci_tools_version,
        operating_system=_required_string(runtime_raw, "operatingSystem", "runtime"),
        architecture=_required_string(runtime_raw, "architecture", "runtime"),
        github_runner=_required_string(runtime_raw, "githubRunner", "runtime"),
    )
    if runtime.operating_system.lower() != "windows":
        raise WindowsConfigError("runtime.operatingSystem must be windows")

    batteries_raw = raw.get("batteries")
    if not isinstance(batteries_raw, dict) or not batteries_raw:
        raise WindowsConfigError("batteries must contain at least one battery")

    cases_by_name = {case.name: case for case in plan.cases}
    include: list[dict[str, Any]] = []
    for battery_name, selection in batteries_raw.items():
        if battery_name not in cases_by_name:
            raise WindowsConfigError(f"Unknown Windows battery: {battery_name}")
        if not isinstance(selection, dict):
            raise WindowsConfigError(f"batteries.{battery_name} must be a mapping")
        selected_profiles = selection.get("profiles")
        if (
            not isinstance(selected_profiles, list)
            or not selected_profiles
            or not all(isinstance(item, str) and item for item in selected_profiles)
        ):
            raise WindowsConfigError(
                f"batteries.{battery_name}.profiles must be a non-empty list of strings"
            )

        payload = cases_by_name[battery_name].matrix_payload(runtime)
        if payload["runner"] != "standard":
            raise WindowsConfigError(
                f"Windows battery {battery_name} must use the standard runner"
            )
        if payload["services"]:
            raise WindowsConfigError(
                f"Windows battery {battery_name} has battery-level services; keep it on Linux"
            )

        profiles_by_name = {profile["name"]: profile for profile in payload["profiles"]}
        resolved_profiles: list[dict[str, Any]] = []
        for profile_name in selected_profiles:
            profile = profiles_by_name.get(profile_name)
            if profile is None:
                raise WindowsConfigError(
                    f"Unknown profile {battery_name}/{profile_name}"
                )
            if profile.get("services"):
                raise WindowsConfigError(
                    f"Windows profile {battery_name}/{profile_name} requires services; keep it on Linux"
                )
            resolved_profiles.append(profile)

        selected_names = {profile["name"] for profile in resolved_profiles}
        filtered_ignored: list[dict[str, Any]] = []
        for ignored in payload.get("ignoredTests", []):
            scoped_profiles = ignored.get("profiles")
            if not scoped_profiles:
                filtered_ignored.append(ignored)
                continue
            matching_profiles = [name for name in scoped_profiles if name in selected_names]
            if matching_profiles:
                normalized_ignored = dict(ignored)
                normalized_ignored["profiles"] = matching_profiles
                filtered_ignored.append(normalized_ignored)

        payload["profiles"] = resolved_profiles
        payload["ignoredTests"] = filtered_ignored
        payload["tests"] = resolved_profiles[0]["tests"]
        include.append(payload)

    return {"include": include}, runtime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("main_config", type=Path)
    parser.add_argument("windows_config", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        matrix, runtime = resolve_windows_matrix(args.main_config, args.windows_config)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
        print(f"matrix={json.dumps(matrix, separators=(',', ':'))}")
        print(f"duckdb_version={runtime.duckdb_version}")
        print(f"ci_tools_version={runtime.ci_tools_version}")
        print(f"github_runner={runtime.github_runner}")
        return 0
    except (OSError, yaml.YAMLError, ConfigError, WindowsConfigError) as exc:
        print(f"Invalid Windows QA configuration: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
