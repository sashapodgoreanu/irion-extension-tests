#!/usr/bin/env python3
"""Create Azure test containers/filesystems and upload pinned upstream fixtures.

The script authenticates with the Service Principal supplied to the job, creates
the configured Blob targets, uploads every file from the pinned ``duckdb-azure/data``
directory, mirrors fixed upstream namespaces, and prepares CLI/access-token auth.
ADLS/ABFSS targets are optional; when they are not configured, upstream tests
protected by require-env ABFSS_* skip naturally.
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
_OPTIONAL_ABFSS_ENV = (
    "ABFSS_STORAGE_ACCOUNT",
    "ABFSS_DATA_DIR",
    "ABFSS_TEMP_DIR",
)
_CONTAINER = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$")
_UPSTREAM_DATA_CONTAINER = "duckdblabs-data"
_UPSTREAM_DATA_PREFIX = "common/azure_data"
_UPSTREAM_WRITE_CONTAINER = "duckdblabs-write-testing"


class AzureBootstrapError(RuntimeError):
    pass


def required_environment(environment: dict[str, str]) -> dict[str, str]:
    missing = [name for name in _REQUIRED_ENV if not environment.get(name, "").strip()]
    if missing:
        raise AzureBootstrapError(
            "missing required Azure bootstrap variable(s): " + ", ".join(missing)
        )

    values = {name: environment[name].strip() for name in _REQUIRED_ENV}
    optional = {
        name: environment.get(name, "").strip()
        for name in _OPTIONAL_ABFSS_ENV
    }
    configured = [name for name, value in optional.items() if value]
    if configured and len(configured) != len(_OPTIONAL_ABFSS_ENV):
        missing_optional = [name for name, value in optional.items() if not value]
        raise AzureBootstrapError(
            "ABFSS bootstrap configuration must provide all or none of: "
            + ", ".join(_OPTIONAL_ABFSS_ENV)
            + "; missing: "
            + ", ".join(missing_optional)
        )
    if configured:
        values.update(optional)
    return values


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


def az_executable() -> str:
    executable = shutil.which("az")
    if executable is None:
        raise AzureBootstrapError("Azure CLI 'az' is not installed on this runner")
    return executable


def run_az(arguments: list[str], *, capture: bool = False) -> str:
    process = subprocess.run(
        [az_executable(), *arguments],
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or f"exit code {process.returncode}"
        raise AzureBootstrapError(f"Azure CLI command failed: {detail}")
    return process.stdout.strip() if capture else ""


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


def storage_access_token() -> str:
    token = run_az(
        [
            "account",
            "get-access-token",
            "--resource",
            "https://storage.azure.com/",
            "--query",
            "accessToken",
            "--output",
            "tsv",
            "--only-show-errors",
        ],
        capture=True,
    )
    if not token:
        raise AzureBootstrapError("Azure CLI returned an empty Storage access token")
    return token


def azure_config_directory(environment: dict[str, str]) -> str:
    configured = environment.get("AZURE_CONFIG_DIR", "").strip()
    if configured:
        return configured
    home = environment.get("USERPROFILE", "").strip() or environment.get("HOME", "").strip()
    if not home:
        home = str(Path.home())
    return str(Path(home) / ".azure")


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


def append_runtime_auth_environment(
    path: Path, access_token: str, config_dir: str
) -> None:
    for name, value in (
        ("AZURE_ACCESS_TOKEN", access_token),
        ("AZURE_CONFIG_DIR", config_dir),
    ):
        if "\n" in value or "\r" in value:
            raise AzureBootstrapError(f"{name} contains an unsupported newline")
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"::add-mask::{access_token}")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("AZ_CLI_LOGGED_IN=1\n")
        handle.write(f"AZURE_ACCESS_TOKEN={access_token}\n")
        handle.write(f"AZURE_CONFIG_DIR={config_dir}\n")


def abfss_enabled(inputs: dict[str, str]) -> bool:
    return "ABFSS_STORAGE_ACCOUNT" in inputs


def storage_targets(inputs: dict[str, str]) -> list[tuple[str, str, str]]:
    """Return unique (account, container, prefix) fixture upload targets."""
    targets: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(account: str, container: str, prefix: str) -> None:
        key = (account, container, prefix)
        if key not in seen:
            seen.add(key)
            targets.append(key)

    account = inputs["AZ_STORAGE_ACCOUNT"]
    container, prefix = split_storage_path(inputs["AZ_DATA_DIR"], "AZ_DATA_DIR")
    add(account, container, prefix)

    if abfss_enabled(inputs):
        abfss_account = inputs["ABFSS_STORAGE_ACCOUNT"]
        abfss_container, abfss_prefix = split_storage_path(
            inputs["ABFSS_DATA_DIR"], "ABFSS_DATA_DIR"
        )
        add(abfss_account, abfss_container, abfss_prefix)

    # Some pinned upstream tests still refer directly to duckdblabs-data. Mirror
    # that namespace only in storage accounts that are actually configured.
    add(inputs["AZ_STORAGE_ACCOUNT"], _UPSTREAM_DATA_CONTAINER, _UPSTREAM_DATA_PREFIX)
    if abfss_enabled(inputs):
        add(inputs["ABFSS_STORAGE_ACCOUNT"], _UPSTREAM_DATA_CONTAINER, _UPSTREAM_DATA_PREFIX)

    return targets


def writable_containers(inputs: dict[str, str]) -> set[tuple[str, str]]:
    targets: set[tuple[str, str]] = set()

    for path_name in ("AZ_DATA_DIR", "AZ_TEMP_DIR"):
        container, _ = split_storage_path(inputs[path_name], path_name)
        targets.add((inputs["AZ_STORAGE_ACCOUNT"], container))

    if abfss_enabled(inputs):
        for path_name in ("ABFSS_DATA_DIR", "ABFSS_TEMP_DIR"):
            container, _ = split_storage_path(inputs[path_name], path_name)
            targets.add((inputs["ABFSS_STORAGE_ACCOUNT"], container))

    # Pinned upstream write/VFS tests still address these containers literally.
    # Prepare them only in configured accounts.
    targets.add((inputs["AZ_STORAGE_ACCOUNT"], _UPSTREAM_DATA_CONTAINER))
    targets.add((inputs["AZ_STORAGE_ACCOUNT"], _UPSTREAM_WRITE_CONTAINER))
    if abfss_enabled(inputs):
        targets.add((inputs["ABFSS_STORAGE_ACCOUNT"], _UPSTREAM_DATA_CONTAINER))
        targets.add((inputs["ABFSS_STORAGE_ACCOUNT"], _UPSTREAM_WRITE_CONTAINER))
    return targets


def bootstrap(source_root: Path, environment: dict[str, str]) -> int:
    inputs = required_environment(environment)
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

    for account, container in sorted(writable_containers(inputs)):
        ensure_container(account, container)

    targets = storage_targets(inputs)
    for account, container, prefix in targets:
        for file_path in files:
            upload_fixture(account, container, prefix, fixture_root, file_path)

    token = storage_access_token()
    github_env = environment.get("GITHUB_ENV", "").strip()
    if github_env:
        append_runtime_auth_environment(
            Path(github_env), token, azure_config_directory(environment)
        )

    message = (
        "Azure cloud fixtures ready "
        f"az_account={inputs['AZ_STORAGE_ACCOUNT']} az_data={inputs['AZ_DATA_DIR']} "
        f"az_temp={inputs['AZ_TEMP_DIR']} "
        f"abfss_enabled={str(abfss_enabled(inputs)).lower()} "
        f"upload_targets={len(targets)} files={len(files)}"
    )
    if abfss_enabled(inputs):
        message += (
            f" abfss_account={inputs['ABFSS_STORAGE_ACCOUNT']}"
            f" abfss_data={inputs['ABFSS_DATA_DIR']}"
            f" abfss_temp={inputs['ABFSS_TEMP_DIR']}"
        )
    print(message)
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
