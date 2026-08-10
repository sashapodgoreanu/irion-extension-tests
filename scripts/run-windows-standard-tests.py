#!/usr/bin/env python3
"""Run service-free standard SQLLogicTest profiles with native Windows DuckDB."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PREPARE_BATTERY = REPOSITORY_ROOT / "scripts" / "prepare-test-battery.py"
PREPARE_PROFILE = REPOSITORY_ROOT / "scripts" / "prepare-standard-profile.py"
REQUIREMENT_CHECKER = REPOSITORY_ROOT / "scripts" / "check-test-requirements.py"
PROBE_VALIDATOR = REPOSITORY_ROOT / "scripts" / "validate-extension-probe.py"


class WindowsTestError(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def run_checked(
    command: list[str],
    *,
    env: dict[str, str],
    cwd: Path,
    log_path: Path | None = None,
) -> None:
    if log_path is None:
        completed = subprocess.run(command, cwd=cwd, env=env, check=False)
    else:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as log:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
    if completed.returncode != 0:
        rendered = " ".join(command)
        raise WindowsTestError(
            f"Command failed with exit code {completed.returncode}: {rendered}"
        )


def read_sql(path: Path) -> str:
    return "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    )


def validate_portable_battery(battery: dict[str, Any]) -> None:
    name = battery.get("name", "<unknown>")
    if battery.get("runner") != "standard":
        raise WindowsTestError(f"Windows battery {name} must use the standard runner")
    if battery.get("services"):
        raise WindowsTestError(
            f"Windows battery {name} has services; keep container-backed coverage on Linux"
        )
    profiles = battery.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise WindowsTestError(f"Windows battery {name} has no profiles")
    for profile in profiles:
        if profile.get("services"):
            raise WindowsTestError(
                f"Windows profile {name}/{profile.get('name')} has services; keep it on Linux"
            )


def append_summary(name: str, profile_timings: list[tuple[str, float]]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as summary:
        summary.write(f"### Windows SQLLogicTest: {name}\n\n")
        summary.write("| Profile | Duration |\n|---|---:|\n")
        for profile, seconds in profile_timings:
            summary.write(f"| `{profile}` | {seconds:.1f}s |\n")
        summary.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("battery_json", type=Path)
    parser.add_argument("upstream_root", type=Path)
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("runtime_dir", type=Path)
    parser.add_argument("log_dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        battery = read_json(args.battery_json)
        if not isinstance(battery, dict):
            raise WindowsTestError("Battery JSON must contain an object")
        validate_portable_battery(battery)

        upstream_root = args.upstream_root.resolve()
        artifact_dir = args.artifact_dir.resolve()
        runtime_dir = args.runtime_dir.resolve()
        log_dir = args.log_dir.resolve()
        duckdb = artifact_dir / "bin" / "duckdb.exe"
        unittest = artifact_dir / "bin" / "unittest.exe"
        for required in (duckdb, unittest, upstream_root, PREPARE_BATTERY, PREPARE_PROFILE):
            if not required.exists():
                raise WindowsTestError(f"Required Windows QA input is missing: {required}")

        config_dir = runtime_dir / "battery-config"
        home_dir = runtime_dir / "home"
        temp_dir = runtime_dir / "tmp"
        profiles_dir = runtime_dir / "profiles"
        for directory in (config_dir, home_dir, temp_dir, profiles_dir, log_dir):
            directory.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["HOME"] = str(home_dir)
        env["USERPROFILE"] = str(home_dir)
        env["TEMP"] = str(temp_dir)
        env["TMP"] = str(temp_dir)

        run_checked(
            [sys.executable, str(PREPARE_BATTERY), str(args.battery_json), str(config_dir)],
            env=env,
            cwd=REPOSITORY_ROOT,
        )

        install_sql = read_sql(config_dir / "install-extensions.sql")
        init_sql = read_sql(config_dir / "init-extensions.sql")
        probe_sql = (
            f"{install_sql}\n{init_sql}\n"
            "SELECT extension_name, installed, loaded, extension_version, install_mode, installed_from "
            "FROM duckdb_extensions() ORDER BY extension_name;"
        )
        probe_csv = log_dir / "extensions.csv"
        probe_stderr = log_dir / "extensions-stderr.log"
        with (
            probe_csv.open("w", encoding="utf-8", newline="") as probe_log,
            probe_stderr.open("w", encoding="utf-8") as probe_error_log,
        ):
            completed = subprocess.run(
                [str(duckdb), "-csv", "-header", "-c", probe_sql],
                cwd=REPOSITORY_ROOT,
                env=env,
                stdout=probe_log,
                stderr=probe_error_log,
                text=True,
                check=False,
            )
        if completed.returncode != 0:
            raise WindowsTestError(
                f"DuckDB extension installation/loading failed with exit code {completed.returncode}"
            )
        run_checked(
            [
                sys.executable,
                str(PROBE_VALIDATOR),
                str(probe_csv),
                str(config_dir / "extensions.json"),
            ],
            env=env,
            cwd=REPOSITORY_ROOT,
        )

        profiles = read_json(config_dir / "profiles.json")
        if not isinstance(profiles, list):
            raise WindowsTestError("Generated profiles metadata must contain a list")

        timings: list[tuple[str, float]] = []
        for profile in profiles:
            profile_name = profile["name"]
            profile_config = profiles_dir / f"{profile_name}.json"
            run_checked(
                [
                    sys.executable,
                    str(PREPARE_PROFILE),
                    str(config_dir / "profiles.json"),
                    profile_name,
                    str(upstream_root),
                    str(profile_config),
                    str(config_dir / "extensions.json"),
                    str(config_dir / "profile-skips.json"),
                    str(config_dir),
                ],
                env=env,
                cwd=REPOSITORY_ROOT,
            )

            started = time.perf_counter()
            profile_log = log_dir / f"unittest-{profile_name}.log"
            run_checked(
                [
                    str(unittest),
                    "--test-config",
                    str(profile_config),
                    "--test-dir",
                    str(upstream_root),
                    profile["tests"],
                ],
                env=env,
                cwd=REPOSITORY_ROOT,
                log_path=profile_log,
            )
            elapsed = time.perf_counter() - started
            timings.append((profile_name, elapsed))
            run_checked(
                [
                    sys.executable,
                    str(REQUIREMENT_CHECKER),
                    str(profile_log),
                    str(config_dir / "extensions.json"),
                ],
                env=env,
                cwd=REPOSITORY_ROOT,
            )

        append_summary(str(battery["name"]), timings)
        return 0
    except (OSError, json.JSONDecodeError, KeyError, TypeError, WindowsTestError) as exc:
        print(f"Windows SQLLogicTest execution failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
