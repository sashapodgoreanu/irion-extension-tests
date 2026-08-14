#!/usr/bin/env python3
"""Create Azure test containers and upload the pinned upstream fixtures.

The script authenticates with the Service Principal already supplied to the job,
creates the configured data/write containers if needed, and uploads every file
from the pinned duckdb-azure ``data/`` directory below the configured data path.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

_REQUIRED_ENV = (
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "AZ_STORAGE_ACCOUNT",
    "AZ_DATA_DIR",
    "AZ_TEMP_DIR",
)
_CONTAINER = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$")


class AzureBootstrapError(RuntimeError):
    pass


def required_environment(environment: dict[str, str]) -> dict[str, str]:
    missing = [name for name in _REQUIRED_ENV if not environment.get(name, "").strip()]
    if missing:
        raise AzureBootstrapError(
            "missing required Azure bootstrap variable(s): " + ", ".join(missing)
        )
    return {name: environment[name].strip() for name in _REQUIRED_ENV}


def split_storage_path(value: str, name: str) -> tuple[str, str]:
    normalized = value.strip().strip("/")
    if not normalized or "://" in normalized:
        raise AzureBootstrapError(f"{name} must be a container/path: {value!r}")
    parts = PurePosixPath(normalized).parts
    container = parts[0]
    if not _CONTAINER.fullmatch(container):
        raise AzureBootstrapError(
            f"{name} has an invalid Azure container name: {container!r}"
        )
    prefix = "/".join(parts[1:])
    return container, prefix


def run_az(arguments: list[str]) -> None:
    executable = shutil.which("az")
    if executable is None:
        raise AzureBootstrapError("Azure CLI 'az' is not installed on this runner")
    process = subprocess.run(
        [executable, *arguments],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or f"exit code {process.returncode}"
        raise AzureBootstrapError(f"Azure CLI command failed: {detail}")


def login(inputs: dict[str, str]) -> None:
    run_az(
        [
            "login",
            "--service-principal",
            "--username",
            inputs["AZURE_CLIENT_ID"],
            "--password",
            inputs["AZURE_CLIENT_SECRET"],
            "--tenant",
            inputs["AZURE_TENANT_ID"],
            "--allow-no-subscriptions",
            "--only-show-errors",
            "--output",
            "none",
        ]
    )


def ensure_container(account: str, container: str) -> None:
    run_az(
        [
            "storage",
            "container",
            "create",
            "--account-name",
            account,
            "--name",
            container,
            "--auth-mode",
            "login",
            "--only-show-errors",
            "--output",
            "none",
        ]
    )


def blob_name(prefix: str, relative: Path) -> str:
    suffix = relative.as_posix()
    return f"{prefix}/{suffix}" if prefix else suffix


def upload_fixture(
    account: str,
    container: str,
    prefix: str,
    fixture_root: Path,
    file_path: Path,
) -> None:
    remote_name = blob_name(prefix, file_path.relative_to(fixture_root))
    run_az(
        [
            "storage",
            "blob",
            "upload",
            "--account-name",
            account,
            "--container-name",
            container,
            "--name",
            remote_name,
            "--file",
            str(file_path),
            "--auth-mode",
            "login",
            "--overwrite",
            "true",
            "--only-show-errors",
            "--output",
            "none",
        ]
    )


def bootstrap(source_root: Path, environment: dict[str, str]) -> int:
    inputs = required_environment(environment)
    data_container, data_prefix = split_storage_path(inputs["AZ_DATA_DIR"], "AZ_DATA_DIR")
    temp_container, _ = split_storage_path(inputs["AZ_TEMP_DIR"], "AZ_TEMP_DIR")
    fixture_root = source_root / "data"
    if not fixture_root.is_dir():
        raise AzureBootstrapError(
            f"upstream Azure fixture directory is missing: {fixture_root}"
        )

    files = sorted(path for path in fixture_root.rglob("*") if path.is_file())
    if not files:
        raise AzureBootstrapError(f"no Azure fixtures found under {fixture_root}")
    if not (fixture_root / "l.parquet").is_file():
        raise AzureBootstrapError("required upstream fixture data/l.parquet is missing")

    login(inputs)
    account = inputs["AZ_STORAGE_ACCOUNT"]
    for container in sorted({data_container, temp_container}):
        ensure_container(account, container)

    for file_path in files:
        upload_fixture(account, data_container, data_prefix, fixture_root, file_path)

    print(
        "Azure cloud fixtures ready "
        f"account={account} data={inputs['AZ_DATA_DIR']} "
        f"temp={inputs['AZ_TEMP_DIR']} files={len(files)}"
    )
    return len(files)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        bootstrap(args.source_root.resolve(), dict(os.environ))
        return 0
    except AzureBootstrapError as exc:
        print(f"Azure test data bootstrap failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
