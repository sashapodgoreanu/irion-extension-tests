#!/usr/bin/env python3
"""Run a standard DuckDB extension SQLLogicTest profile natively.

The target DuckDB and unittest binaries always execute on the host OS. Linux or
WSL helpers may prepare external infrastructure, but they are not used to launch
the binaries under test.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parent
SQLLOGIC_SUFFIXES = (".test", ".test_slow", ".test_coverage")
FAILED_TEST_SUMMARY = re.compile(
    r"test cases?:.*\|\s*[1-9][0-9]* failed", re.IGNORECASE
)


class RunnerError(RuntimeError):
    pass


class Logger:
    def __init__(self, path: Path, battery: str) -> None:
        self.path = path
        self.battery = battery
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, level: str, message: str) -> None:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        line = f"{timestamp} [{level}] [{self.battery}] {message}"
        print(line, file=sys.stderr, flush=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def info(self, message: str) -> None:
        self.write("INFO", message)

    def error(self, message: str) -> None:
        self.write("ERROR", message)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sql_from_file(path: Path) -> str:
    return " ".join(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    )


def platform_binary(artifact_dir: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return artifact_dir / "bin" / f"{name}{suffix}"


def child_environment(runtime_home: Path) -> dict[str, str]:
    env = dict(os.environ)
    runtime_home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(runtime_home)
    env["TMPDIR"] = str(runtime_home.parent / "tmp")
    Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        # DuckDB resolves its extension directory from the Windows home as well
        # as HOME. Scope USERPROFILE only to child processes, never globally.
        env["USERPROFILE"] = str(runtime_home)
        env["TEMP"] = env["TMPDIR"]
        env["TMP"] = env["TMPDIR"]
    return env


def run_logged(
    command: list[str],
    *,
    logger: Logger,
    log_file: Path,
    env: dict[str, str],
    cwd: Path | None = None,
    check: bool = True,
    append: bool = False,
) -> int:
    printable = subprocess.list2cmdline(command) if os.name == "nt" else " ".join(command)
    logger.info(f"exec cwd={cwd or Path.cwd()} command={printable}")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with log_file.open(mode, encoding="utf-8", errors="replace") as handle:
        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line)
            handle.write(line)
        return_code = process.wait()
    logger.info(f"exit_code={return_code} log={log_file}")
    if check and return_code != 0:
        raise RunnerError(f"command failed with exit code {return_code}: {printable}")
    return return_code


def assert_unittest_passed(log_file: Path) -> None:
    text = log_file.read_text(encoding="utf-8", errors="replace")
    match = FAILED_TEST_SUMMARY.search(text)
    if match:
        raise RunnerError(
            f"DuckDB unittest reported failing test cases in {log_file}: {match.group(0)}"
        )


def adapt_bigquery_tests(upstream_root: Path, logger: Logger) -> None:
    test_root = upstream_root / "test" / "sql"
    files = sorted(
        path
        for path in test_root.rglob("*")
        if path.is_file() and path.name.endswith(SQLLOGIC_SUFFIXES)
    )
    require_count = 0
    location_count = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        filtered = [line for line in lines if line.strip() != "require bigquery"]
        require_count += len(lines) - len(filtered)
        text = "".join(filtered)
        location_count += text.count("europe-west3")
        path.write_text(text.replace("europe-west3", "EU"), encoding="utf-8")
    if require_count == 0:
        raise RunnerError("No BigQuery SQLLogicTest requirement guards were found")

    replacements = (
        (
            test_root / "storage" / "attach_public_dataset.test",
            "billing_project=${BQ_TEST_BILLING_PROJECT}",
            "billing_project='${BQ_TEST_BILLING_PROJECT}'",
        ),
        (
            test_root / "functions" / "function_bigquery_jobs.test",
            "<REGEX>:[a-zA-Z0-9]+",
            "<REGEX>:[a-zA-Z0-9-]+",
        ),
    )
    for path, old, new in replacements:
        text = path.read_text(encoding="utf-8")
        if old not in text:
            raise RunnerError(f"BigQuery adaptation anchor was not found: {path}: {old}")
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
    logger.info(
        f"BigQuery source adapted require_directives={require_count} normalized_locations={location_count}"
    )


def verify_upstream_ref(upstream_root: Path, expected: str, logger: Logger) -> None:
    if len(expected) != 40 or any(ch not in "0123456789abcdefABCDEF" for ch in expected):
        logger.info(f"upstream ref is not a commit SHA; pin={expected}")
        return
    actual = subprocess.check_output(
        ["git", "-C", str(upstream_root), "rev-parse", "HEAD"], text=True
    ).strip()
    logger.info(f"upstream commit expected={expected} actual={actual}")
    if actual.lower() != expected.lower():
        raise RunnerError(f"upstream checkout must be {expected}; found {actual}")


def move_ignored_tests(
    runtime_config: Path, upstream_root: Path, ignored_root: Path, log_dir: Path, logger: Logger
) -> None:
    source = runtime_config / "ignored-global.tsv"
    if not source.is_file():
        return
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        relative, reason = line.split("\t", 1)
        original = upstream_root / relative
        destination = ignored_root / relative
        if not original.is_file():
            raise RunnerError(f"configured ignored test is missing: {relative}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(original), str(destination))
        with (log_dir / "ignored-tests.tsv").open("a", encoding="utf-8") as handle:
            handle.write(f"{relative}\t{reason}\n")
        logger.info(f"ignored test moved path={relative} reason={reason}")


def locate_extension_platform_dir(runtime_home: Path, duckdb_version: str) -> Path:
    version_root = runtime_home / ".duckdb" / "extensions" / duckdb_version
    if not version_root.is_dir():
        raise RunnerError(f"DuckDB extension version directory was not created: {version_root}")
    candidates = [
        path
        for path in version_root.iterdir()
        if path.is_dir() and any(path.glob("*.duckdb_extension*"))
    ]
    if len(candidates) != 1:
        raise RunnerError(
            f"expected exactly one installed extension platform directory under {version_root}; "
            f"found {[path.name for path in candidates]}"
        )
    return candidates[0]


def prepare_local_extension_repo(
    source_dir: Path, runtime_root: Path, duckdb_version: str, logger: Logger
) -> Path:
    local_repo = runtime_root / "repository"
    target = local_repo / duckdb_version / source_dir.name
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, target)
    logger.info(f"local extension repository source={source_dir} target={target}")
    return local_repo


def validate_probe(
    duckdb: Path,
    install_sql: str,
    init_sql: str,
    extension_csv: Path,
    extensions_json: Path,
    env: dict[str, str],
    logger: Logger,
) -> None:
    sql = (
        f"{install_sql} {init_sql} "
        "SELECT extension_name, installed, loaded, extension_version, install_mode, installed_from "
        "FROM duckdb_extensions() ORDER BY extension_name;"
    )
    run_logged(
        [str(duckdb), "-csv", "-header", "-c", sql],
        logger=logger,
        log_file=extension_csv,
        env=env,
    )
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "validate-extension-probe.py"),
            str(extension_csv),
            str(extensions_json),
        ],
        env=env,
        check=True,
    )
    logger.info("extension probe validated")


def profile_rows(runtime_config: Path) -> Iterable[tuple[str, str]]:
    for line in (runtime_config / "profiles.tsv").read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield tuple(line.split("\t", 1))  # type: ignore[return-value]


def external_profile_services() -> set[str]:
    raw = os.environ.get("QA_EXTERNAL_PROFILE_SERVICES", "")
    return {value.strip() for value in raw.split(",") if value.strip()}


def validate_external_profile_services(profiles: list[dict], logger: Logger) -> None:
    if os.name != "nt":
        return
    required = {profile["name"] for profile in profiles if profile.get("services")}
    if not required:
        return
    hosted = external_profile_services()
    missing = required - hosted
    if missing:
        raise RunnerError(
            "profile-scoped WSL infrastructure is not hosted for: "
            + ",".join(sorted(missing))
        )
    logger.info(
        "external profile infrastructure available profiles=" + ",".join(sorted(required))
    )


def ducklake_test_files(upstream_root: Path) -> list[Path]:
    test_root = upstream_root / "test" / "sql"
    files = sorted(
        path
        for path in test_root.rglob("*")
        if path.is_file() and path.name.endswith(SQLLOGIC_SUFFIXES)
    )
    if not files:
        raise RunnerError("No DuckLake PostgreSQL SQLLogicTest files were found")
    return files


def reset_ducklake_postgres(
    env: dict[str, str], log_file: Path, logger: Logger
) -> None:
    if os.name != "nt":
        raise RunnerError("native DuckLake PostgreSQL reset helper is only expected on Windows")
    distro = env.get("QA_WSL_DISTRO", "")
    helper = env.get("QA_WSL_DUCKLAKE_RESET_HELPER", "")
    if not distro:
        raise RunnerError("QA_WSL_DISTRO is required for DuckLake PostgreSQL isolation")
    if not helper:
        raise RunnerError("QA_WSL_DUCKLAKE_RESET_HELPER is required for DuckLake PostgreSQL isolation")

    forwarded = []
    for name in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE", "PGSSLMODE"):
        value = env.get(name)
        if not value:
            raise RunnerError(f"{name} is required for DuckLake PostgreSQL isolation")
        forwarded.append(f"{name}={value}")

    run_logged(
        [
            "wsl.exe",
            "-d",
            distro,
            "-u",
            "root",
            "--",
            "env",
            *forwarded,
            "bash",
            helper,
        ],
        logger=logger,
        log_file=log_file,
        env=env,
        append=True,
    )


def run_ducklake_postgres_isolated(
    unittest: Path,
    config: Path,
    upstream_root: Path,
    log_dir: Path,
    env: dict[str, str],
    logger: Logger,
) -> Path:
    files = ducklake_test_files(upstream_root)
    unittest_log = log_dir / "unittest-postgres.log"
    reset_log = log_dir / "postgres-reset.log"
    unittest_log.write_text("", encoding="utf-8")
    reset_log.write_text("", encoding="utf-8")
    logger.info(
        f"DuckLake PostgreSQL process/database isolation files={len(files)}"
    )

    for index, test_file in enumerate(files, start=1):
        relative = test_file.relative_to(upstream_root).as_posix()
        logger.info(f"DuckLake PostgreSQL isolated test [{index}/{len(files)}] path={relative}")
        reset_ducklake_postgres(env, reset_log, logger)
        run_logged(
            [
                str(unittest),
                "--test-config",
                str(config),
                "--test-dir",
                str(upstream_root),
                relative,
            ],
            logger=logger,
            log_file=unittest_log,
            env=env,
            cwd=upstream_root,
            append=True,
        )
        assert_unittest_passed(unittest_log)

    return unittest_log


def run_profile(
    test_name: str,
    profile_name: str,
    test_filter: str,
    unittest: Path,
    config: Path,
    upstream_root: Path,
    log_dir: Path,
    extensions_json: Path,
    env: dict[str, str],
    logger: Logger,
) -> None:
    if os.name == "nt" and test_name == "ducklake" and profile_name == "postgres":
        unittest_log = run_ducklake_postgres_isolated(
            unittest, config, upstream_root, log_dir, env, logger
        )
    else:
        unittest_log = log_dir / f"unittest-{profile_name}.log"
        run_logged(
            [
                str(unittest),
                "--test-config",
                str(config),
                "--test-dir",
                str(upstream_root),
                test_filter,
            ],
            logger=logger,
            log_file=unittest_log,
            env=env,
            cwd=upstream_root,
        )
        assert_unittest_passed(unittest_log)

    subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "check-test-requirements.py"),
            str(unittest_log),
            str(extensions_json),
        ],
        env=env,
        check=True,
    )


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} TEST_NAME UPSTREAM_ROOT", file=sys.stderr)
        return 2

    test_name = sys.argv[1]
    upstream_root = Path(sys.argv[2]).resolve()
    artifact_dir = Path(os.environ.get("ARTIFACT_DIR", "build/artifact")).resolve()
    runtime_config = Path(os.environ["BATTERY_RUNTIME_CONFIG_DIR"]).resolve()
    duckdb_version = os.environ["DUCKDB_VERSION"]
    runner_temp = Path(
        os.environ.get("RUNNER_TEMP", str(REPOSITORY_ROOT / "build" / "runtime"))
    ).resolve()
    runtime_root = runner_temp / test_name
    log_dir = REPOSITORY_ROOT / "build" / "logs" / test_name
    ignored_root = runner_temp / "ignored-tests" / test_name
    logger = Logger(log_dir / "standard-runner.log", test_name)

    try:
        duckdb = platform_binary(artifact_dir, "duckdb")
        unittest = platform_binary(artifact_dir, "unittest")
        if not duckdb.is_file():
            raise RunnerError(f"native DuckDB binary is missing: {duckdb}")
        if not unittest.is_file():
            raise RunnerError(f"native unittest binary is missing: {unittest}")
        if not upstream_root.is_dir():
            raise RunnerError(f"upstream root is missing: {upstream_root}")

        runtime_root.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
        ignored_root.mkdir(parents=True, exist_ok=True)
        env = child_environment(runtime_root / "home")
        logger.info(
            f"native standard runner started os={os.name} duckdb={duckdb} unittest={unittest} "
            f"source={upstream_root} runtime={runtime_root}"
        )

        battery = read_json(runtime_config / "battery.json")
        verify_upstream_ref(upstream_root, battery.get("pin", "self"), logger)
        move_ignored_tests(runtime_config, upstream_root, ignored_root, log_dir, logger)

        if test_name == "bigquery":
            if os.environ.get("BQ_TEST_PROJECT"):
                env["BQ_TEST_BILLING_PROJECT"] = os.environ["BQ_TEST_PROJECT"]
            credentials = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            if credentials:
                env["BQ_TEST_SA_KEY_PATH"] = credentials
            adapt_bigquery_tests(upstream_root, logger)

        # Delta and Iceberg still require their fixture generators to be split
        # from the old Bash runner before Windows can use this native path.
        if os.name == "nt" and test_name in {"delta", "iceberg"}:
            raise RunnerError(
                f"{test_name} fixture preparation has not yet been detached from the Linux test runner"
            )

        profiles = read_json(runtime_config / "profiles.json")
        if not isinstance(profiles, list):
            raise RunnerError("profiles.json must contain a list")
        validate_external_profile_services(profiles, logger)

        install_script = runtime_config / "install-extensions.sql"
        init_script = runtime_config / "init-extensions.sql"
        extensions_json = runtime_config / "extensions.json"
        install_sql = sql_from_file(install_script)
        init_sql = sql_from_file(init_script)
        extension_csv = log_dir / "extensions.csv"

        for source in (
            "battery.json",
            "extensions.json",
            "services.json",
            "prerequisites.json",
            "capabilities.json",
            "profiles.json",
            "install-extensions.sql",
            "init-extensions.sql",
        ):
            shutil.copy2(runtime_config / source, log_dir / source)
        for source in runtime_config.glob("init-profile-*.sql"):
            shutil.copy2(source, log_dir / source.name)

        validate_probe(duckdb, install_sql, init_sql, extension_csv, extensions_json, env, logger)
        extension_dir = locate_extension_platform_dir(runtime_root / "home", duckdb_version)
        local_repo = prepare_local_extension_repo(
            extension_dir, runtime_root, duckdb_version, logger
        )
        env["LOCAL_EXTENSION_REPO"] = str(local_repo)

        for profile_name, test_filter in profile_rows(runtime_config):
            config = runtime_root / "profiles" / f"{profile_name}.json"
            config.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"preparing profile={profile_name} filter={test_filter}")
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "prepare-standard-profile.py"),
                    str(runtime_config / "profiles.json"),
                    profile_name,
                    str(upstream_root),
                    str(config),
                    str(extensions_json),
                    str(runtime_config / "profile-skips.json"),
                    str(runtime_config),
                ],
                env=env,
                check=True,
            )
            shutil.copy2(config, log_dir / f"profile-{profile_name}.json")
            profile_services = runtime_config / f"profile-services-{profile_name}.json"
            if profile_services.is_file():
                shutil.copy2(
                    profile_services, log_dir / f"profile-services-{profile_name}.json"
                )

            run_profile(
                test_name,
                profile_name,
                test_filter,
                unittest,
                config,
                upstream_root,
                log_dir,
                extensions_json,
                env,
                logger,
            )
            logger.info(f"profile passed name={profile_name}")

        logger.info("native standard runner completed successfully")
        return 0
    except (
        OSError,
        KeyError,
        json.JSONDecodeError,
        RunnerError,
        subprocess.CalledProcessError,
    ) as exc:
        logger.error(f"native standard runner failed: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
