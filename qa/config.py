"""Load, validate, type and compile the DuckDB extension QA configuration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .plan import (
    ExecutionCase,
    ExecutionContract,
    ExecutionExtension,
    ExecutionIgnoredTest,
    ExecutionPlan,
    ExecutionRuntime,
    ExecutionSource,
)

EXTENSION_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
REPOSITORY_NAME = re.compile(r"^[^/\s]+/[^/\s]+$")
VALID_RUNNERS = frozenset({"standard", "postgres-scanner", "mssql-release"})
VALID_SETUPS = frozenset(
    {"none", "httpfs-services", "ducklake-catalogs", "postgres-17", "sqlserver-2022"}
)
VALID_PROFILES = frozenset({"sqlite", "postgres"})


class ConfigError(ValueError):
    """Raised when the QA configuration violates its schema or semantic contracts."""


@dataclass(frozen=True, slots=True)
class DuckDbConfig:
    version: str
    ci_tools_version: str


@dataclass(frozen=True, slots=True)
class ExtensionConfig:
    name: str
    is_used: bool
    install_from: str | None = None

    def runtime_payload(self) -> dict[str, str]:
        payload = {"name": self.name}
        if self.install_from is not None:
            payload["installFrom"] = self.install_from
        return payload

    def execution_extension(self) -> ExecutionExtension:
        return ExecutionExtension(name=self.name, install_from=self.install_from)


@dataclass(frozen=True, slots=True)
class IgnoredTestConfig:
    path: str
    reason: str
    profiles: tuple[str, ...] = ()

    def matrix_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"path": self.path, "reason": self.reason}
        if self.profiles:
            payload["profiles"] = list(self.profiles)
        return payload

    def execution_ignored_test(self) -> ExecutionIgnoredTest:
        return ExecutionIgnoredTest(
            path=self.path,
            reason=self.reason,
            profiles=self.profiles,
        )


@dataclass(frozen=True, slots=True)
class BatteryConfig:
    name: str
    is_enabled: bool
    runner: str
    repository: str
    pin: str
    tests: str
    submodules: str
    setup: str
    extensions: tuple[ExtensionConfig, ...]
    ignored_tests: tuple[IgnoredTestConfig, ...]


@dataclass(frozen=True, slots=True)
class QaConfig:
    schema_version: int
    duckdb: DuckDbConfig
    default_extensions: tuple[ExtensionConfig, ...]
    test_batteries: tuple[BatteryConfig, ...]


# Compatibility aliases retained while callers migrate to execution-plan terminology.
ResolvedBattery = ExecutionCase
ResolvedConfig = ExecutionPlan


def _schema_path(error: ValidationError) -> str:
    if not error.absolute_path:
        return "root"
    return "root." + ".".join(str(part) for part in error.absolute_path)


def _format_schema_error(error: ValidationError) -> str:
    return f"{_schema_path(error)}: {error.message}"


def _load_schema(schema_path: Path) -> Mapping[str, Any]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"unable to load configuration schema {schema_path}: {exc}") from exc
    if not isinstance(schema, dict):
        raise ConfigError(f"configuration schema {schema_path} must contain a JSON object")
    Draft202012Validator.check_schema(schema)
    return schema


def _validate_schema(data: Any, schema_path: Path) -> Mapping[str, Any]:
    schema = _load_schema(schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(data),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        raise ConfigError(_format_schema_error(errors[0]))
    if not isinstance(data, dict):
        raise ConfigError("root must be a mapping")
    return data


def _normalize_submodules(value: bool | str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _parse_extension(raw: Mapping[str, Any], path: str) -> ExtensionConfig:
    name = raw["name"].strip()
    if not EXTENSION_NAME.fullmatch(name):
        raise ConfigError(f"{path}.name contains unsupported characters: {name}")
    install_from = raw.get("installFrom")
    if install_from is not None:
        install_from = install_from.strip()
        if not EXTENSION_NAME.fullmatch(install_from):
            raise ConfigError(f"{path}.installFrom is invalid: {install_from}")
    return ExtensionConfig(name=name, is_used=raw["isUsed"], install_from=install_from)


def _parse_extensions(
    raw: Sequence[Mapping[str, Any]], path: str
) -> tuple[ExtensionConfig, ...]:
    extensions: list[ExtensionConfig] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        extension = _parse_extension(item, f"{path}[{index}]")
        if extension.name in seen:
            raise ConfigError(f"{path} contains duplicate extension {extension.name}")
        seen.add(extension.name)
        extensions.append(extension)
    return tuple(extensions)


def _parse_ignored_test(raw: Mapping[str, Any], path: str) -> IgnoredTestConfig:
    test_path = raw["path"].strip()
    reason = raw["reason"].strip()
    if test_path.startswith("/") or ".." in Path(test_path).parts:
        raise ConfigError(f"{path}.path must stay inside the upstream checkout")
    if any(character in test_path or character in reason for character in ("\t", "\n")):
        raise ConfigError(f"{path} cannot contain tabs or newlines")
    profiles = tuple(raw.get("profiles", ()))
    unsupported = sorted(set(profiles) - VALID_PROFILES)
    if unsupported:
        raise ConfigError(
            f"{path}.profiles contains unsupported profile {unsupported[0]}; "
            f"supported profiles: {', '.join(sorted(VALID_PROFILES))}"
        )
    return IgnoredTestConfig(path=test_path, reason=reason, profiles=profiles)


def _parse_ignored_tests(
    raw: Sequence[Mapping[str, Any]], path: str
) -> tuple[IgnoredTestConfig, ...]:
    ignored_tests: list[IgnoredTestConfig] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for index, item in enumerate(raw):
        ignored = _parse_ignored_test(item, f"{path}[{index}]")
        key = (ignored.path, tuple(sorted(ignored.profiles)))
        if key in seen:
            raise ConfigError(f"{path} contains duplicate ignored test {ignored.path}")
        seen.add(key)
        ignored_tests.append(ignored)
    return tuple(ignored_tests)


def parse_config(data: Mapping[str, Any]) -> QaConfig:
    duckdb_raw = data["duckdb"]
    duckdb = DuckDbConfig(
        version=duckdb_raw["version"].strip(),
        ci_tools_version=duckdb_raw["ciToolsVersion"].strip(),
    )
    defaults = _parse_extensions(data["defaultExtensions"], "defaultExtensions")

    batteries: list[BatteryConfig] = []
    for name, raw in data["testBatteries"].items():
        if not EXTENSION_NAME.fullmatch(name):
            raise ConfigError(f"testBatteries contains invalid name {name!r}")
        path = f"testBatteries.{name}"
        runner = raw["runner"].strip()
        if runner not in VALID_RUNNERS:
            raise ConfigError(f"{path}.runner is unsupported: {runner}")
        repository = raw["repository"].strip()
        if not REPOSITORY_NAME.fullmatch(repository):
            raise ConfigError(f"{path}.repository must use owner/name form")
        setup = raw.get("setup", "none").strip()
        if setup not in VALID_SETUPS:
            raise ConfigError(
                f"{path}.setup is unsupported: {setup}; "
                f"supported setups: {', '.join(sorted(VALID_SETUPS))}"
            )
        batteries.append(
            BatteryConfig(
                name=name,
                is_enabled=raw["isEnabled"],
                runner=runner,
                repository=repository,
                pin=raw["pin"].strip(),
                tests=raw["tests"].strip(),
                submodules=_normalize_submodules(raw.get("submodules", False)),
                setup=setup,
                extensions=_parse_extensions(raw.get("extensions", ()), f"{path}.extensions"),
                ignored_tests=_parse_ignored_tests(
                    raw.get("ignoredTests", ()), f"{path}.ignoredTests"
                ),
            )
        )

    return QaConfig(
        schema_version=data["schemaVersion"],
        duckdb=duckdb,
        default_extensions=defaults,
        test_batteries=tuple(batteries),
    )


def load_config(config_path: Path, schema_path: Path | None = None) -> QaConfig:
    if schema_path is None:
        schema_path = Path(__file__).resolve().parents[1] / "schemas" / "extensions-v1.schema.json"
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(str(exc)) from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML: {exc}") from exc
    validated = _validate_schema(data, schema_path)
    return parse_config(validated)


def _active_extensions(
    extensions: Sequence[ExtensionConfig],
) -> tuple[ExtensionConfig, ...]:
    return tuple(extension for extension in extensions if extension.is_used)


def _merge_extensions(
    default_extensions: Sequence[ExtensionConfig],
    battery_extensions: Sequence[ExtensionConfig],
    path: str,
) -> tuple[ExtensionConfig, ...]:
    result: list[ExtensionConfig] = []
    by_name: dict[str, ExtensionConfig] = {}
    for source_name, extensions in (
        ("defaultExtensions", default_extensions),
        (f"{path}.extensions", battery_extensions),
    ):
        for extension in extensions:
            existing = by_name.get(extension.name)
            if existing is None:
                by_name[extension.name] = extension
                result.append(extension)
                continue
            if (
                existing.install_from is not None
                and extension.install_from is not None
                and existing.install_from != extension.install_from
            ):
                raise ConfigError(
                    f"{source_name} conflicts with the resolved installFrom for "
                    f"{extension.name}: {existing.install_from} != {extension.install_from}"
                )
            if existing.install_from is None and extension.install_from is not None:
                replacement = ExtensionConfig(
                    name=existing.name,
                    is_used=True,
                    install_from=extension.install_from,
                )
                by_name[extension.name] = replacement
                result[result.index(existing)] = replacement
    return tuple(result)


def resolve_config(config: QaConfig) -> ExecutionPlan:
    """Compile validated configuration into a versioned execution plan."""

    active_defaults = _active_extensions(config.default_extensions)
    cases: list[ExecutionCase] = []
    for battery in config.test_batteries:
        if not battery.is_enabled:
            continue
        path = f"testBatteries.{battery.name}"
        resolved_extensions = _merge_extensions(
            active_defaults,
            _active_extensions(battery.extensions),
            path,
        )
        if not resolved_extensions:
            raise ConfigError(f"{path} resolves to an empty extension set")
        cases.append(
            ExecutionCase(
                name=battery.name,
                source=ExecutionSource(
                    repository=battery.repository,
                    pin=battery.pin,
                    submodules=battery.submodules,
                ),
                contract=ExecutionContract(
                    runner=battery.runner,
                    setup=battery.setup,
                    tests=battery.tests,
                ),
                extensions=tuple(
                    extension.execution_extension() for extension in resolved_extensions
                ),
                ignored_tests=tuple(
                    ignored.execution_ignored_test() for ignored in battery.ignored_tests
                ),
            )
        )
    if not cases:
        raise ConfigError("at least one test battery must have isEnabled: true")
    return ExecutionPlan(
        runtime=ExecutionRuntime(
            duckdb_version=config.duckdb.version,
            ci_tools_version=config.duckdb.ci_tools_version,
        ),
        cases=tuple(cases),
    )
