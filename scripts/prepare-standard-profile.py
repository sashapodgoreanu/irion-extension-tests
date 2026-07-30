#!/usr/bin/env python3
"""Build one SQLLogicTest config from a declarative standard-runner profile."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


class ProfileError(ValueError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def init_sql(path: Path) -> str:
    return " ".join(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    )


def add_profile_skips(config: dict[str, Any], additions: list[dict[str, str]]) -> None:
    if not additions:
        return
    skip_tests = list(config.get("skip_tests", []))
    grouped: dict[str, list[str]] = {}
    for item in additions:
        grouped.setdefault(item["reason"], []).append(item["path"])
    for reason, paths in grouped.items():
        skip_tests.append({"reason": reason, "paths": paths})
    config["skip_tests"] = skip_tests


def combine_upstream_on_init(
    config: dict[str, Any], init_script: Path, destination: Path
) -> Path:
    """Preserve upstream on_init while prepending the resolved extension loads.

    DuckDB's test runner parses init_script by replacing the on_init option with
    the file contents. Keeping both JSON keys therefore silently discards the
    upstream catalog setup when init_script appears later in the object.
    """

    existing_on_init = config.pop("on_init", "")
    if existing_on_init and not isinstance(existing_on_init, str):
        raise ProfileError("upstream on_init must be a string")
    if not existing_on_init:
        return init_script

    destination.parent.mkdir(parents=True, exist_ok=True)
    combined_init = destination.with_suffix(".init.sql")
    base_sql = init_script.read_text(encoding="utf-8").rstrip()
    combined_init.write_text(
        f"{base_sql}\n\n-- Preserved from the upstream test config.\n"
        f"{existing_on_init.strip()}\n",
        encoding="utf-8",
    )
    return combined_init.resolve()


def main() -> int:
    if len(sys.argv) != 8:
        print(
            f"usage: {sys.argv[0]} PROFILES_JSON PROFILE UPSTREAM_ROOT DEST_CONFIG "
            "EXTENSIONS_JSON PROFILE_SKIPS_JSON RUNTIME_CONFIG_DIR",
            file=sys.stderr,
        )
        return 2

    profiles_path = Path(sys.argv[1])
    profile_name = sys.argv[2]
    upstream_root = Path(sys.argv[3]).resolve()
    destination = Path(sys.argv[4])
    extensions_path = Path(sys.argv[5])
    skips_path = Path(sys.argv[6])
    runtime_config_dir = Path(sys.argv[7]).resolve()

    try:
        profiles = read_json(profiles_path)
        extensions = read_json(extensions_path)
        profile_skips = read_json(skips_path)
        if not isinstance(profiles, list):
            raise ProfileError("profiles JSON must be a list")
        profile = next((item for item in profiles if item.get("name") == profile_name), None)
        if not isinstance(profile, dict):
            raise ProfileError(f"profile {profile_name} was not found")
        test_config = profile.get("testConfig")
        if not isinstance(test_config, dict):
            raise ProfileError(f"profile {profile_name} has no testConfig")
        init_script = runtime_config_dir / profile["initScript"]
        if not init_script.is_file():
            raise ProfileError(f"profile init script is missing: {init_script}")
        connection_sql = init_sql(init_script)
        kind = test_config.get("kind")

        if kind == "generated":
            config: dict[str, Any] = {
                "description": test_config.get(
                    "description", f"{profile_name} compatibility profile"
                ),
                "autoloading": "all",
                "init_script": str(init_script),
                "on_new_connection": connection_sql,
                "statically_loaded_extensions": list(
                    test_config["staticallyLoadedExtensions"]
                ),
                "summarize_failures": True,
            }
        elif kind == "upstream":
            source = (upstream_root / test_config["path"]).resolve()
            try:
                source.relative_to(upstream_root)
            except ValueError as exc:
                raise ProfileError("upstream config escaped the checkout") from exc
            config = read_json(source)
            if not isinstance(config, dict):
                raise ProfileError("upstream test config must be an object")
            config["autoloading"] = "all"
            config["summarize_failures"] = True
            loaded_extensions = list(config.get("statically_loaded_extensions", []))
            for name in ["core_functions", "parquet"] + [
                item["name"] for item in extensions
            ]:
                if name not in loaded_extensions:
                    loaded_extensions.append(name)
            config["statically_loaded_extensions"] = loaded_extensions
            existing_connection_sql = config.get("on_new_connection", "")
            if existing_connection_sql and not isinstance(existing_connection_sql, str):
                raise ProfileError("upstream on_new_connection must be a string")
            config["on_new_connection"] = " ".join(
                value for value in (connection_sql, existing_connection_sql) if value
            )
            config["init_script"] = str(
                combine_upstream_on_init(config, init_script, destination)
            )
        else:
            raise ProfileError(f"unsupported profile testConfig kind: {kind}")

        additions = profile_skips.get(profile_name, [])
        if not isinstance(additions, list):
            raise ProfileError("profile skip metadata must be a list")
        add_profile_skips(config, additions)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        return 0
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ProfileError) as exc:
        print(f"Unable to prepare profile {profile_name}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
