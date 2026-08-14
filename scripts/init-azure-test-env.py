#!/usr/bin/env python3
"""Initialize the Azure environment used by the DuckDB Azure test battery.

Only the externally managed Azure identity/storage inputs are required:

- AZURE_TENANT_ID
- AZURE_CLIENT_ID
- AZURE_CLIENT_SECRET
- AZ_STORAGE_ACCOUNT

All remaining values are derived here so GitHub repository configuration stays
small and the Linux/Windows runners use the same cloud-test contract.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from pathlib import Path

REQUIRED_INPUTS = (
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "AZ_STORAGE_ACCOUNT",
)

FIXTURE_ROOT = "duckdblabs-data/common/azure_data"
WRITE_ROOT = "duckdblabs-write-testing/extension/azure"

_SAFE_SUFFIX = re.compile(r"[^A-Za-z0-9._-]+")


class AzureEnvironmentError(ValueError):
    """Raised when the Azure test environment cannot be initialized."""


def required_inputs(environment: dict[str, str]) -> dict[str, str]:
    missing = [name for name in REQUIRED_INPUTS if not environment.get(name, "").strip()]
    if missing:
        raise AzureEnvironmentError(
            "missing required Azure test environment variable(s): " + ", ".join(missing)
        )
    return {name: environment[name].strip() for name in REQUIRED_INPUTS}


def execution_suffix(environment: dict[str, str]) -> str:
    parts = [
        environment.get("GITHUB_RUN_ID", ""),
        environment.get("GITHUB_RUN_ATTEMPT", ""),
        environment.get("RUNNER_OS", ""),
    ]
    populated = [part.strip() for part in parts if part and part.strip()]
    if populated:
        raw = "-".join(populated)
    else:
        raw = f"local-{uuid.uuid4().hex[:12]}"
    return _SAFE_SUFFIX.sub("-", raw).strip("-")


def resolve_environment(environment: dict[str, str]) -> dict[str, str]:
    inputs = required_inputs(environment)
    suffix = execution_suffix(environment)
    storage_account = inputs["AZ_STORAGE_ACCOUNT"]
    temp_dir = f"{WRITE_ROOT}/{suffix}"

    return {
        **inputs,
        "AZURE_AUTH_ENV": "1",
        "AZURE_PROVIDER": "cloud",
        "AZURE_PROTOCOL": "az",
        "AZURE_STORAGE_ACCOUNT": storage_account,
        "AZ_DATA_DIR": FIXTURE_ROOT,
        "AZ_TEMP_DIR": temp_dir,
        "DATA_DIR": FIXTURE_ROOT,
        "TEMP_DIR": temp_dir,
    }


def append_github_environment(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for name, value in values.items():
            if "\n" in value or "\r" in value:
                raise AzureEnvironmentError(f"{name} contains an unsupported newline")
            handle.write(f"{name}={value}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--github-env",
        type=Path,
        default=Path(os.environ["GITHUB_ENV"]) if os.environ.get("GITHUB_ENV") else None,
        help="GitHub Actions environment file. Defaults to GITHUB_ENV when available.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        values = resolve_environment(dict(os.environ))
        if args.github_env is None:
            for name, value in values.items():
                if name == "AZURE_CLIENT_SECRET":
                    continue
                print(f"{name}={value}")
        else:
            append_github_environment(args.github_env, values)
            print(
                "Azure test environment initialized "
                f"account={values['AZ_STORAGE_ACCOUNT']} "
                f"provider={values['AZURE_PROVIDER']} "
                f"temp_dir={values['AZ_TEMP_DIR']}"
            )
        return 0
    except AzureEnvironmentError as exc:
        print(f"Azure test environment initialization failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
