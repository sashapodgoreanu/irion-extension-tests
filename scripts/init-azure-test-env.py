#!/usr/bin/env python3
"""Initialize the Azure environment used by the DuckDB Azure test battery.

The shared cross-platform battery intentionally exercises Blob/Azure cloud paths on
both Linux and Windows. ADLS/ABFSS coverage is disabled in this runner: upstream
tests guarded by require-env ABFSS_* therefore skip naturally even when legacy
repository variables are still configured.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

REQUIRED_INPUTS = (
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "AZ_STORAGE_ACCOUNT",
    "AZ_DATA_DIR",
    "AZ_TEMP_DIR",
)

PUBLIC_AZ_STORAGE_ACCOUNT = "duckdbtesting"

WSL_FORWARD_VARIABLES = (
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "AZURE_ACCESS_TOKEN",
    "AZURE_CONFIG_DIR",
    "AZ_CLI_LOGGED_IN",
    "AZ_STORAGE_ACCOUNT",
    "AZURE_AUTH_ENV",
    "AZURE_PROVIDER",
    "AZURE_PROTOCOL",
    "AZURE_STORAGE_ACCOUNT",
    "AZ_DATA_DIR",
    "AZ_TEMP_DIR",
    "DATA_DIR",
    "TEMP_DIR",
    "DUCKDB_AZURE_PUBLIC_CONTAINER_AVAILABLE",
    "PUBLIC_AZ_STORAGE_ACCOUNT",
)

_LINUX_CA_SOURCE = Path("/etc/ssl/certs/ca-certificates.crt")
_LINUX_CA_TARGET = Path("/etc/pki/tls/certs/ca-bundle.crt")
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


def storage_root(value: str, name: str) -> str:
    normalized = value.strip().strip("/")
    if not normalized:
        raise AzureEnvironmentError(f"{name} must not be empty")
    if "://" in normalized:
        raise AzureEnvironmentError(
            f"{name} must be a container/path, not a URI: {value}"
        )
    return normalized


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


def wsl_environment(existing: str) -> str:
    entries = [entry for entry in existing.split(":") if entry]
    seen = set(entries)
    for name in WSL_FORWARD_VARIABLES:
        if name not in seen:
            entries.append(name)
            seen.add(name)
    return ":".join(entries)


def resolve_environment(environment: dict[str, str]) -> dict[str, str]:
    inputs = required_inputs(environment)
    suffix = execution_suffix(environment)
    storage_account = inputs["AZ_STORAGE_ACCOUNT"]
    data_dir = storage_root(inputs["AZ_DATA_DIR"], "AZ_DATA_DIR")
    temp_root = storage_root(inputs["AZ_TEMP_DIR"], "AZ_TEMP_DIR")
    temp_dir = f"{temp_root}/{suffix}"

    values = {
        **inputs,
        "AZURE_AUTH_ENV": "1",
        "AZURE_PROVIDER": "cloud",
        "AZURE_PROTOCOL": "az",
        "AZURE_STORAGE_ACCOUNT": storage_account,
        "AZ_DATA_DIR": data_dir,
        "AZ_TEMP_DIR": temp_dir,
        "DATA_DIR": data_dir,
        "TEMP_DIR": temp_dir,
        # Match DuckDB Azure's own cloud workflow for the unauthenticated test.
        "DUCKDB_AZURE_PUBLIC_CONTAINER_AVAILABLE": "1",
        "PUBLIC_AZ_STORAGE_ACCOUNT": PUBLIC_AZ_STORAGE_ACCOUNT,
    }

    # ABFSS_* is intentionally not copied from the input environment. This is
    # the contract for the shared CI battery: ABFSS tests skip, while every
    # remaining cloud test runs on both operating systems.
    if environment.get("RUNNER_OS", "").strip().lower() == "windows":
        values["WSLENV"] = wsl_environment(environment.get("WSLENV", ""))
    return values


def _run_privileged(command: list[str]) -> None:
    prefix: list[str] = []
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None or geteuid() != 0:
        sudo = shutil.which("sudo")
        if sudo is None:
            raise AzureEnvironmentError(
                "sudo is required to configure the Linux CA compatibility path"
            )
        prefix.append(sudo)

    process = subprocess.run(
        [*prefix, *command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or f"exit code {process.returncode}"
        raise AzureEnvironmentError(
            "unable to configure Linux CA compatibility path: " + detail
        )


def configure_linux_ca_bundle(
    environment: dict[str, str],
    *,
    source: Path = _LINUX_CA_SOURCE,
    target: Path = _LINUX_CA_TARGET,
) -> bool:
    """Provide the CA path expected by the Azure/libcurl Linux runtime."""

    if environment.get("RUNNER_OS", "").strip().lower() != "linux":
        return False
    if environment.get("GITHUB_ACTIONS", "").strip().lower() != "true":
        return False
    if not source.is_file():
        raise AzureEnvironmentError(f"Linux CA bundle is missing: {source}")
    if target.is_file():
        return False

    _run_privileged(["mkdir", "-p", str(target.parent)])
    _run_privileged(["ln", "-sfn", str(source), str(target)])
    return True


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
        environment = dict(os.environ)
        linux_ca_compat = configure_linux_ca_bundle(environment)
        values = resolve_environment(environment)
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
                f"data_dir={values['AZ_DATA_DIR']} "
                f"temp_dir={values['AZ_TEMP_DIR']} "
                "abfss_enabled=false "
                f"public_account={values['PUBLIC_AZ_STORAGE_ACCOUNT']} "
                f"linux_ca_compat={str(linux_ca_compat).lower()}"
            )
        return 0
    except AzureEnvironmentError as exc:
        print(f"Azure test environment initialization failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
