#!/usr/bin/env python3
"""Adapt a pinned DuckLake catalog config to the resolved extension set."""

from __future__ import annotations

import json
import sys
from pathlib import Path


class ConfigError(ValueError):
    pass


def main() -> int:
    if len(sys.argv) != 7:
        print(
            f"usage: {sys.argv[0]} SOURCE_CONFIG DEST_CONFIG EXTENSIONS_JSON "
            "PROFILE_SKIPS_JSON PROFILE INIT_SCRIPT",
            file=sys.stderr,
        )
        return 2

    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    extensions_path = Path(sys.argv[3])
    profile_skips_path = Path(sys.argv[4])
    profile = sys.argv[5]
    init_script = Path(sys.argv[6])

    try:
        config = json.loads(source.read_text(encoding="utf-8"))
        extensions = json.loads(extensions_path.read_text(encoding="utf-8"))
        profile_skips = json.loads(profile_skips_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ConfigError("upstream config must be an object")
        if not isinstance(extensions, list):
            raise ConfigError("extensions JSON must be a list")
        if not isinstance(profile_skips, dict):
            raise ConfigError("profile skips JSON must be an object")

        config["autoloading"] = "all"
        config["summarize_failures"] = True

        loaded_extensions = list(config.get("statically_loaded_extensions", []))
        for name in ["core_functions", "parquet"] + [item["name"] for item in extensions]:
            if name not in loaded_extensions:
                loaded_extensions.append(name)
        config["statically_loaded_extensions"] = loaded_extensions

        generated_connection_sql = " ".join(
            line.strip()
            for line in init_script.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("--")
        )
        existing_connection_sql = config.get("on_new_connection", "")
        if existing_connection_sql and not isinstance(existing_connection_sql, str):
            raise ConfigError("upstream on_new_connection must be a string")
        config["on_new_connection"] = " ".join(
            value for value in (generated_connection_sql, existing_connection_sql) if value
        )

        additions = profile_skips.get(profile, [])
        if additions:
            skip_tests = list(config.get("skip_tests", []))
            grouped: dict[str, list[str]] = {}
            for item in additions:
                grouped.setdefault(item["reason"], []).append(item["path"])
            for reason, paths in grouped.items():
                skip_tests.append({"reason": reason, "paths": paths})
            config["skip_tests"] = skip_tests

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        return 0
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ConfigError) as exc:
        print(f"Unable to prepare DuckLake {profile} config: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
