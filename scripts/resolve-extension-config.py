#!/usr/bin/env python3
"""Validate config/extensions.yml and emit the GitHub Actions matrix."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

EXTENSION_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
REPOSITORY_NAME = re.compile(r"^[^/\s]+/[^/\s]+$")
VALID_RUNNERS = {"standard", "postgres-scanner", "mssql-release"}
VALID_SETUPS = {
    "none",
    "httpfs-services",
    "ducklake-catalogs",
    "postgres-17",
    "sqlserver-2022",
}
VALID_PROFILES = {"sqlite", "postgres"}


class ConfigError(ValueError):
    pass


def require_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must be a mapping")
    return value


def require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigError(f"{path} must be a list")
    return value


def require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path} must be a non-empty string")
    return value.strip()


def require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{path} must be true or false")
    return value


def normalize_extension(value: Any, path: str) -> dict[str, str]:
    item = require_mapping(value, path)
    name = require_string(item.get("name"), f"{path}.name")
    if not EXTENSION_NAME.fullmatch(name):
        raise ConfigError(f"{path}.name contains unsupported characters: {name}")

    is_used = require_bool(item.get("isUsed"), f"{path}.isUsed")
    normalized: dict[str, str] = {"name": name}
    if "installFrom" in item:
        install_from = require_string(item["installFrom"], f"{path}.installFrom")
        if not EXTENSION_NAME.fullmatch(install_from):
            raise ConfigError(f"{path}.installFrom is invalid: {install_from}")
        normalized["installFrom"] = install_from
    normalized["isUsed"] = "true" if is_used else "false"
    return normalized


def normalize_extensions(values: Any, path: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, value in enumerate(require_list(values, path)):
        item = normalize_extension(value, f"{path}[{index}]")
        name = item["name"]
        if name in seen:
            raise ConfigError(f"{path} contains duplicate extension {name}")
        seen.add(name)
        result.append(item)
    return result


def normalize_ignored_tests(values: Any, path: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for index, value in enumerate(require_list(values, path)):
        item = require_mapping(value, f"{path}[{index}]")
        test_path = require_string(item.get("path"), f"{path}[{index}].path")
        reason = require_string(item.get("reason"), f"{path}[{index}].reason")
        if test_path.startswith("/") or ".." in Path(test_path).parts:
            raise ConfigError(f"{path}[{index}].path must stay inside the upstream checkout")
        if "\t" in test_path or "\n" in test_path or "\t" in reason or "\n" in reason:
            raise ConfigError(f"{path}[{index}] cannot contain tabs or newlines")

        profiles_value = item.get("profiles", [])
        profiles: list[str] = []
        for profile_index, profile_value in enumerate(
            require_list(profiles_value, f"{path}[{index}].profiles")
        ):
            profile = require_string(
                profile_value,
                f"{path}[{index}].profiles[{profile_index}]",
            )
            if profile not in VALID_PROFILES:
                raise ConfigError(
                    f"{path}[{index}].profiles contains unsupported profile {profile}; "
                    f"supported profiles: {', '.join(sorted(VALID_PROFILES))}"
                )
            if profile not in profiles:
                profiles.append(profile)

        key = (test_path, tuple(sorted(profiles)))
        if key in seen:
            raise ConfigError(f"{path} contains duplicate ignored test {test_path}")
        seen.add(key)
        normalized: dict[str, Any] = {"path": test_path, "reason": reason}
        if profiles:
            normalized["profiles"] = profiles
        result.append(normalized)
    return result


def normalize_submodules(value: Any, path: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = require_string(value, path)
    if text not in {"true", "false", "recursive"}:
        raise ConfigError(f"{path} must be true, false, or recursive")
    return text


def active_extensions(values: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in values:
        if item["isUsed"] != "true":
            continue
        active = {"name": item["name"]}
        if "installFrom" in item:
            active["installFrom"] = item["installFrom"]
        result.append(active)
    return result


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} CONFIG_YAML", file=sys.stderr)
        return 2

    config_path = Path(sys.argv[1])
    try:
        root = require_mapping(
            yaml.safe_load(config_path.read_text(encoding="utf-8")), "root"
        )
        schema_version = root.get("schemaVersion")
        if schema_version != 1:
            raise ConfigError("schemaVersion must be 1")

        duckdb = require_mapping(root.get("duckdb"), "duckdb")
        duckdb_version = require_string(duckdb.get("version"), "duckdb.version")
        ci_tools_version = require_string(
            duckdb.get("ciToolsVersion"), "duckdb.ciToolsVersion"
        )

        defaults = normalize_extensions(
            root.get("defaultExtensions"), "defaultExtensions"
        )
        active_defaults = active_extensions(defaults)
        active_default_names = {item["name"] for item in active_defaults}

        batteries = require_mapping(root.get("testBatteries"), "testBatteries")
        matrix: list[dict[str, Any]] = []
        for name, raw_battery in batteries.items():
            if not isinstance(name, str) or not EXTENSION_NAME.fullmatch(name):
                raise ConfigError(f"testBatteries contains invalid name {name!r}")
            path = f"testBatteries.{name}"
            battery = require_mapping(raw_battery, path)
            is_enabled = require_bool(battery.get("isEnabled"), f"{path}.isEnabled")
            runner = require_string(battery.get("runner"), f"{path}.runner")
            if runner not in VALID_RUNNERS:
                raise ConfigError(f"{path}.runner is unsupported: {runner}")
            repository = require_string(
                battery.get("repository"), f"{path}.repository"
            )
            if not REPOSITORY_NAME.fullmatch(repository):
                raise ConfigError(f"{path}.repository must use owner/name form")
            pin = require_string(battery.get("pin"), f"{path}.pin")
            tests = require_string(battery.get("tests"), f"{path}.tests")
            submodules = normalize_submodules(
                battery.get("submodules", False), f"{path}.submodules"
            )
            setup = require_string(battery.get("setup", "none"), f"{path}.setup")
            if setup not in VALID_SETUPS:
                raise ConfigError(
                    f"{path}.setup is unsupported: {setup}; "
                    f"supported setups: {', '.join(sorted(VALID_SETUPS))}"
                )
            extensions = normalize_extensions(
                battery.get("extensions", []), f"{path}.extensions"
            )
            duplicate_defaults = active_default_names.intersection(
                item["name"] for item in extensions
            )
            if duplicate_defaults:
                duplicates = ", ".join(sorted(duplicate_defaults))
                raise ConfigError(
                    f"{path}.extensions repeats active default extensions: {duplicates}"
                )
            ignored_tests = normalize_ignored_tests(
                battery.get("ignoredTests", []), f"{path}.ignoredTests"
            )

            if not is_enabled:
                continue

            resolved_extensions = active_defaults + active_extensions(extensions)
            if not resolved_extensions:
                raise ConfigError(f"{path} resolves to an empty extension set")
            matrix.append(
                {
                    "name": name,
                    "runner": runner,
                    "repository": repository,
                    "pin": pin,
                    "tests": tests,
                    "submodules": submodules,
                    "setup": setup,
                    "duckdbVersion": duckdb_version,
                    "extensions": resolved_extensions,
                    "ignoredTests": ignored_tests,
                }
            )

        if not matrix:
            raise ConfigError("at least one test battery must have isEnabled: true")

        print("matrix=" + json.dumps({"include": matrix}, separators=(",", ":")))
        print(f"duckdb_version={duckdb_version}")
        print(f"ci_tools_version={ci_tools_version}")
        print("enabled_batteries=" + ",".join(item["name"] for item in matrix))
        return 0
    except (OSError, yaml.YAMLError, ConfigError) as exc:
        print(f"Invalid extension configuration: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
