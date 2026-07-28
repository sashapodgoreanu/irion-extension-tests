"""Load, validate, type and resolve the DuckDB extension QA configuration."""

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
    ExecutionPrerequisite,
    ExecutionProfile,
    ExecutionRuntime,
    ExecutionService,
    ExecutionSource,
)

EXTENSION_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
PROFILE_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
SERVICE_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
REPOSITORY_NAME = re.compile(r"^[^/\s]+/[^/\s]+$")
VALID_RUNNERS = frozenset({"standard", "postgres-scanner", "mssql-release"})
VALID_SERVICE_TYPES = frozenset(
    {"python-http", "squid", "httpfs-minio", "postgres", "sqlserver"}
)
VALID_PREREQUISITE_TYPES = frozenset(
    {"google-bigquery", "external-cloud-account"}
)
SUPPORTED_SCHEMA_VERSION = 3

SERVICE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "python-http": (),
    "squid": ("squid",),
    "httpfs-minio": ("docker-compose",),
    "postgres": ("docker", "postgres-client"),
    "sqlserver": ("docker-compose",),
}
PREREQUISITE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "google-bigquery": ("google-cloud-auth",),
    "external-cloud-account": ("accepted-failure",),
}


class ConfigError(ValueError):
    """Raised when the QA configuration violates schema or semantic contracts."""


@dataclass(frozen=True, slots=True)
class DuckDbConfig:
    version: str
    ci_tools_version: str


@dataclass(frozen=True, slots=True)
class ExtensionConfig:
    name: str
    is_used: bool
    install_from: str | None = None

    def execution_extension(self) -> ExecutionExtension:
        return ExecutionExtension(name=self.name, install_from=self.install_from)


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    name: str
    service_type: str
    options: tuple[tuple[str, Any], ...] = ()

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {"name": self.name, "type": self.service_type}
        result.update(dict(self.options))
        return result

    def execution_service(self) -> ExecutionService:
        return ExecutionService(
            name=self.name,
            service_type=self.service_type,
            options=self.options,
        )


@dataclass(frozen=True, slots=True)
class PrerequisiteConfig:
    prerequisite_type: str

    def execution_prerequisite(self) -> ExecutionPrerequisite:
        return ExecutionPrerequisite(prerequisite_type=self.prerequisite_type)


@dataclass(frozen=True, slots=True)
class GeneratedTestConfig:
    excluded_extensions: tuple[str, ...]
    statically_loaded_extensions: tuple[str, ...]
    description: str | None = None
    kind: str = "generated"

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "kind": self.kind,
            "excludedExtensions": list(self.excluded_extensions),
            "staticallyLoadedExtensions": list(self.statically_loaded_extensions),
        }
        if self.description is not None:
            result["description"] = self.description
        return result


@dataclass(frozen=True, slots=True)
class UpstreamTestConfig:
    path: str
    kind: str = "upstream"

    def payload(self) -> dict[str, str]:
        return {"kind": self.kind, "path": self.path}


TestConfig = GeneratedTestConfig | UpstreamTestConfig


@dataclass(frozen=True, slots=True)
class ProfileConfig:
    name: str
    tests: str
    services: tuple[ServiceConfig, ...] = ()
    test_config: TestConfig | None = None

    def execution_profile(self) -> ExecutionProfile:
        return ExecutionProfile(
            name=self.name,
            tests=self.tests,
            services=tuple(service.execution_service() for service in self.services),
            test_config=self.test_config.payload() if self.test_config is not None else None,
        )


@dataclass(frozen=True, slots=True)
class IgnoredTestConfig:
    path: str
    reason: str
    profiles: tuple[str, ...] = ()

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
    submodules: str
    services: tuple[ServiceConfig, ...]
    prerequisites: tuple[PrerequisiteConfig, ...]
    profiles: tuple[ProfileConfig, ...]
    extensions: tuple[ExtensionConfig, ...]
    ignored_tests: tuple[IgnoredTestConfig, ...]


@dataclass(frozen=True, slots=True)
class QaConfig:
    schema_version: int
    duckdb: DuckDbConfig
    default_extensions: tuple[ExtensionConfig, ...]
    test_batteries: tuple[BatteryConfig, ...]


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


def _ensure_relative_path(value: str, path: str) -> str:
    normalized = value.strip()
    if normalized.startswith("/") or ".." in Path(normalized).parts:
        raise ConfigError(f"{path} must stay inside the upstream checkout")
    return normalized


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


def _parse_service(raw: Mapping[str, Any], path: str) -> ServiceConfig:
    name = raw["name"].strip()
    service_type = raw["type"].strip()
    if not SERVICE_NAME.fullmatch(name):
        raise ConfigError(f"{path}.name contains unsupported characters: {name}")
    if service_type not in VALID_SERVICE_TYPES:
        raise ConfigError(f"{path}.type is unsupported: {service_type}")
    options = tuple(
        sorted(
            ((key, value) for key, value in raw.items() if key not in {"name", "type"}),
            key=lambda item: item[0],
        )
    )
    return ServiceConfig(name=name, service_type=service_type, options=options)


def _parse_services(
    raw: Sequence[Mapping[str, Any]], path: str
) -> tuple[ServiceConfig, ...]:
    services: list[ServiceConfig] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        service = _parse_service(item, f"{path}[{index}]")
        if service.name in seen:
            raise ConfigError(f"{path} contains duplicate service {service.name}")
        seen.add(service.name)
        services.append(service)
    return tuple(services)


def _parse_prerequisites(
    raw: Sequence[Mapping[str, Any]], path: str
) -> tuple[PrerequisiteConfig, ...]:
    prerequisites: list[PrerequisiteConfig] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        prerequisite_type = item["type"].strip()
        if prerequisite_type not in VALID_PREREQUISITE_TYPES:
            raise ConfigError(f"{path}[{index}].type is unsupported: {prerequisite_type}")
        if prerequisite_type in seen:
            raise ConfigError(f"{path} contains duplicate prerequisite {prerequisite_type}")
        seen.add(prerequisite_type)
        prerequisites.append(PrerequisiteConfig(prerequisite_type=prerequisite_type))
    return tuple(prerequisites)


def _parse_test_config(raw: Mapping[str, Any], path: str) -> TestConfig:
    kind = raw["kind"]
    if kind == "generated":
        return GeneratedTestConfig(
            excluded_extensions=tuple(raw.get("excludedExtensions", ())),
            statically_loaded_extensions=tuple(raw.get("staticallyLoadedExtensions", ())),
            description=raw.get("description"),
        )
    if kind == "upstream":
        return UpstreamTestConfig(path=_ensure_relative_path(raw["path"], f"{path}.path"))
    raise ConfigError(f"{path}.kind is unsupported: {kind}")


def _parse_profiles(
    raw: Sequence[Mapping[str, Any]], path: str, runner: str
) -> tuple[ProfileConfig, ...]:
    profiles: list[ProfileConfig] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        item_path = f"{path}[{index}]"
        name = item["name"].strip()
        if not PROFILE_NAME.fullmatch(name):
            raise ConfigError(f"{item_path}.name contains unsupported characters: {name}")
        if name in seen:
            raise ConfigError(f"{path} contains duplicate profile {name}")
        seen.add(name)
        test_config_raw = item.get("testConfig")
        test_config = (
            _parse_test_config(test_config_raw, f"{item_path}.testConfig")
            if test_config_raw is not None
            else None
        )
        if runner == "standard" and test_config is None:
            raise ConfigError(f"{item_path}.testConfig is required for the standard runner")
        services = _parse_services(item.get("services", ()), f"{item_path}.services")
        if runner != "standard" and services:
            raise ConfigError(f"{item_path}.services is only supported by the standard runner")
        profiles.append(
            ProfileConfig(
                name=name,
                tests=item["tests"].strip(),
                services=services,
                test_config=test_config,
            )
        )
    return tuple(profiles)


def _parse_ignored_test(raw: Mapping[str, Any], path: str) -> IgnoredTestConfig:
    test_path = _ensure_relative_path(raw["path"], f"{path}.path")
    reason = raw["reason"].strip()
    if any(character in test_path or character in reason for character in ("\t", "\n")):
        raise ConfigError(f"{path} cannot contain tabs or newlines")
    return IgnoredTestConfig(
        path=test_path,
        reason=reason,
        profiles=tuple(raw.get("profiles", ())),
    )


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
        services = _parse_services(raw["services"], f"{path}.services")
        prerequisites = _parse_prerequisites(
            raw["prerequisites"], f"{path}.prerequisites"
        )
        profiles = _parse_profiles(raw["profiles"], f"{path}.profiles", runner)
        battery_service_names = {service.name for service in services}
        for profile in profiles:
            overlap = sorted(
                battery_service_names & {service.name for service in profile.services}
            )
            if overlap:
                raise ConfigError(
                    f"{path}.profiles.{profile.name}.services duplicates battery service {overlap[0]}"
                )
        profile_names = {profile.name for profile in profiles}
        ignored_tests = _parse_ignored_tests(
            raw.get("ignoredTests", ()), f"{path}.ignoredTests"
        )
        for ignored in ignored_tests:
            unknown_profiles = sorted(set(ignored.profiles) - profile_names)
            if unknown_profiles:
                raise ConfigError(
                    f"{path}.ignoredTests references unknown profile {unknown_profiles[0]}"
                )
        batteries.append(
            BatteryConfig(
                name=name,
                is_enabled=raw["isEnabled"],
                runner=runner,
                repository=repository,
                pin=raw["pin"].strip(),
                submodules=_normalize_submodules(raw.get("submodules", False)),
                services=services,
                prerequisites=prerequisites,
                profiles=profiles,
                extensions=_parse_extensions(
                    raw.get("extensions", ()), f"{path}.extensions"
                ),
                ignored_tests=ignored_tests,
            )
        )

    return QaConfig(
        schema_version=data["schemaVersion"],
        duckdb=duckdb,
        default_extensions=defaults,
        test_batteries=tuple(batteries),
    )


def load_config(config_path: Path, schema_path: Path | None = None) -> QaConfig:
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(str(exc)) from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("root must be a mapping")
    schema_version = data.get("schemaVersion")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise ConfigError(
            f"schemaVersion must be {SUPPORTED_SCHEMA_VERSION}; found {schema_version!r}"
        )
    if schema_path is None:
        schema_path = (
            Path(__file__).resolve().parents[1]
            / "schemas"
            / f"extensions-v{SUPPORTED_SCHEMA_VERSION}.schema.json"
        )
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


def _capabilities(battery: BatteryConfig) -> tuple[str, ...]:
    ordered: list[str] = []

    def add(values: Sequence[str]) -> None:
        for value in values:
            if value not in ordered:
                ordered.append(value)

    for service in battery.services:
        add(SERVICE_CAPABILITIES[service.service_type])
    for profile in battery.profiles:
        for service in profile.services:
            add(SERVICE_CAPABILITIES[service.service_type])
    for prerequisite in battery.prerequisites:
        add(PREREQUISITE_CAPABILITIES[prerequisite.prerequisite_type])
    return tuple(ordered)


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
        resolved_names = {extension.name for extension in resolved_extensions}
        for profile in battery.profiles:
            if isinstance(profile.test_config, GeneratedTestConfig):
                unknown = sorted(
                    set(profile.test_config.excluded_extensions) - resolved_names
                )
                if unknown:
                    raise ConfigError(
                        f"{path}.profiles.{profile.name} excludes unresolved extension {unknown[0]}"
                    )
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
                    services=tuple(
                        service.execution_service() for service in battery.services
                    ),
                    prerequisites=tuple(
                        item.execution_prerequisite()
                        for item in battery.prerequisites
                    ),
                    capabilities=_capabilities(battery),
                    profiles=tuple(
                        profile.execution_profile() for profile in battery.profiles
                    ),
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
