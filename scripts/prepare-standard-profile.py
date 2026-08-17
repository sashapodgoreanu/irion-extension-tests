#!/usr/bin/env python3
"""Build one SQLLogicTest config from a declarative standard-runner profile."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


class ProfileError(ValueError):
    pass


HTTPFS_PROFILE_DESCRIPTION = "HTTPFS compatibility SQL suite"
HTTPFS_PAGING_TEST = Path("test/sql/copy/s3/glob_s3_paging.test_slow")
HTTPFS_REQUEST_COUNT_QUERY = (
    "query IIIII\n"
    "FROM (FROM duckdb_logs_parsed('HTTP') SELECT count(*),"
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def align_httpfs_request_count_test(upstream_root: Path) -> None:
    """Skip only the unstable HTTP request-count assertion from the pinned suite.

    The functional paging/glob assertions remain enabled. DuckDB HTTPFS upstream
    made the same decision in 288f7e88 because glob-result caching can change the
    exact number of ListObjectsV2 requests without changing query correctness.
    """

    path = upstream_root / HTTPFS_PAGING_TEST
    if not path.is_file():
        raise ProfileError(f"HTTPFS paging test is missing: {path}")

    text = path.read_text(encoding="utf-8")
    marker_index = text.find(HTTPFS_REQUEST_COUNT_QUERY)
    if marker_index < 0:
        raise ProfileError(
            "HTTPFS paging request-count assertion no longer matches the pinned suite"
        )

    prefix = text[:marker_index]
    if prefix.rstrip().endswith("mode skip"):
        return

    compatibility_note = (
        "# QA compatibility: upstream skips this exact request-count assertion "
        "because glob caching\n"
        "# changes ListObjectsV2 call counts while the functional glob results "
        "above remain valid.\n"
        "# Upstream reference: duckdb/duckdb-httpfs@288f7e88a264dae8754e5d2dd4528a930876c037\n"
        "mode skip\n\n"
    )
    path.write_text(
        prefix + compatibility_note + text[marker_index:], encoding="utf-8"
    )


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


def resolve_upstream_init_script(
    config: dict[str, Any], upstream_root: Path
) -> Path | None:
    configured = config.pop("init_script", "")
    if configured in (None, ""):
        return None
    if not isinstance(configured, str):
        raise ProfileError("upstream init_script must be a string")

    source = (upstream_root / configured).resolve()
    try:
        source.relative_to(upstream_root)
    except ValueError as exc:
        raise ProfileError("upstream init_script escaped the checkout") from exc
    if not source.is_file():
        raise ProfileError(f"upstream init_script is missing: {source}")
    return source


def combine_upstream_initialization(
    config: dict[str, Any],
    runtime_init_script: Path,
    upstream_root: Path,
    destination: Path,
) -> Path:
    """Combine resolved extension loads with repository-owned initialization.

    DuckDB's test runner parses init_script by replacing the on_init option with
    the file contents. Keeping both JSON keys therefore silently discards the
    upstream catalog setup when init_script appears later in the object. Local
    Irion batteries also keep their initialization SQL in the repository, so a
    relative upstream init_script is resolved and merged into one generated file.
    """

    upstream_init_script = resolve_upstream_init_script(config, upstream_root)
    existing_on_init = config.pop("on_init", "")
    if existing_on_init and not isinstance(existing_on_init, str):
        raise ProfileError("upstream on_init must be a string")
    if upstream_init_script is None and not existing_on_init:
        return runtime_init_script

    destination.parent.mkdir(parents=True, exist_ok=True)
    combined_init = destination.with_suffix(".init.sql")
    sections = [
        runtime_init_script.read_text(encoding="utf-8").rstrip(),
    ]
    if upstream_init_script is not None:
        sections.extend(
            [
                "-- Preserved from the repository test config init_script.",
                upstream_init_script.read_text(encoding="utf-8").strip(),
            ]
        )
    if existing_on_init:
        sections.extend(
            [
                "-- Preserved from the repository test config on_init.",
                existing_on_init.strip(),
            ]
        )
    combined_init.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
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
        if test_config.get("description") == HTTPFS_PROFILE_DESCRIPTION:
            align_httpfs_request_count_test(upstream_root)
        init_script = runtime_config_dir / profile["initScript"]
        if not init_script.is_file():
            raise ProfileError(f"profile init script is missing: {init_script}")
        connection_sql = init_sql(init_script)
        kind = test_config.get("kind")

        if kind == "generated":
            loaded_extensions = list(test_config["staticallyLoadedExtensions"])
            # SQLLogicTest evaluates `require bigquery` against this list. The
            # BigQuery runtime loads the extension dynamically through the
            # generated init script, so expose it to the runner for this profile.
            if (
                test_config.get("description")
                == "Google BigQuery compatibility profile"
                and any(item.get("name") == "bigquery" for item in extensions)
                and "bigquery" not in loaded_extensions
            ):
                loaded_extensions.append("bigquery")
            config: dict[str, Any] = {
                "description": test_config.get(
                    "description", f"{profile_name} compatibility profile"
                ),
                "autoloading": "all",
                "init_script": str(init_script),
                "on_new_connection": connection_sql,
                "statically_loaded_extensions": loaded_extensions,
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
                combine_upstream_initialization(
                    config, init_script, upstream_root, destination
                )
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
