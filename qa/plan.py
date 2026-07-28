"""Versioned execution plan emitted by the DuckDB extension QA compiler."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXECUTION_PLAN_SCHEMA_VERSION = 3


@dataclass(frozen=True, slots=True)
class ExecutionRuntime:
    duckdb_version: str
    ci_tools_version: str

    def payload(self) -> dict[str, str]:
        return {
            "duckdbVersion": self.duckdb_version,
            "ciToolsVersion": self.ci_tools_version,
        }


@dataclass(frozen=True, slots=True)
class ExecutionExtension:
    name: str
    install_from: str | None = None

    def payload(self) -> dict[str, str]:
        result = {"name": self.name}
        if self.install_from is not None:
            result["installFrom"] = self.install_from
        return result


@dataclass(frozen=True, slots=True)
class ExecutionService:
    type: str
    version: str | None = None
    database: str | None = None
    port: int | None = None

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type}
        if self.version is not None:
            result["version"] = self.version
        if self.database is not None:
            result["database"] = self.database
        if self.port is not None:
            result["port"] = self.port
        return result


@dataclass(frozen=True, slots=True)
class ExecutionPrerequisite:
    type: str
    required_variables: tuple[str, ...] = ()

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type}
        if self.required_variables:
            result["requiredVariables"] = list(self.required_variables)
        return result


@dataclass(frozen=True, slots=True)
class ExecutionIgnoredTest:
    path: str
    reason: str
    profiles: tuple[str, ...] = ()

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {"path": self.path, "reason": self.reason}
        if self.profiles:
            result["profiles"] = list(self.profiles)
        return result


@dataclass(frozen=True, slots=True)
class ExecutionSource:
    repository: str
    pin: str
    submodules: str

    def payload(self) -> dict[str, str]:
        return {
            "repository": self.repository,
            "pin": self.pin,
            "submodules": self.submodules,
        }


@dataclass(frozen=True, slots=True)
class ExecutionProfile:
    name: str
    tests: str
    services: tuple[ExecutionService, ...]
    test_config: dict[str, Any] | None

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "tests": self.tests,
            "services": [service.payload() for service in self.services],
        }
        if self.test_config is not None:
            result["testConfig"] = self.test_config
        return result


@dataclass(frozen=True, slots=True)
class ExecutionContract:
    runner: str
    services: tuple[ExecutionService, ...]
    prerequisites: tuple[ExecutionPrerequisite, ...]
    profiles: tuple[ExecutionProfile, ...]
    allow_failure: bool = False
    failure_reason: str | None = None

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "runner": self.runner,
            "services": [service.payload() for service in self.services],
            "prerequisites": [item.payload() for item in self.prerequisites],
            "profiles": [profile.payload() for profile in self.profiles],
            "allowFailure": self.allow_failure,
        }
        if self.failure_reason is not None:
            result["failureReason"] = self.failure_reason
        return result


@dataclass(frozen=True, slots=True)
class ExecutionCase:
    name: str
    source: ExecutionSource
    contract: ExecutionContract
    extensions: tuple[ExecutionExtension, ...]
    ignored_tests: tuple[ExecutionIgnoredTest, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source.payload(),
            "execution": self.contract.payload(),
            "extensions": [extension.payload() for extension in self.extensions],
            "ignoredTests": [ignored.payload() for ignored in self.ignored_tests],
        }

    def matrix_payload(self, duckdb_version: str) -> dict[str, Any]:
        service_types = {service.type for service in self.contract.services}
        prerequisite_types = {item.type for item in self.contract.prerequisites}
        return {
            "name": self.name,
            "runner": self.contract.runner,
            "repository": self.source.repository,
            "pin": self.source.pin,
            "tests": self.contract.profiles[0].tests,
            "submodules": self.source.submodules,
            "duckdbVersion": duckdb_version,
            "services": [service.payload() for service in self.contract.services],
            "prerequisites": [item.payload() for item in self.contract.prerequisites],
            "profiles": [profile.payload() for profile in self.contract.profiles],
            "extensions": [extension.payload() for extension in self.extensions],
            "ignoredTests": [ignored.payload() for ignored in self.ignored_tests],
            "allowFailure": self.contract.allow_failure,
            "failureReason": self.contract.failure_reason or "",
            "requiresGoogleCloud": "google-cloud" in prerequisite_types,
            "requiresHttpfsServices": {"python-http", "squid", "minio"}.issubset(
                service_types
            ),
            "requiresPostgres17": any(
                service.type == "postgres" and service.version == "17"
                for service in self.contract.services
            ),
            "requiresSqlServer2022": any(
                service.type == "sqlserver" and service.version == "2022"
                for service in self.contract.services
            ),
        }


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    runtime: ExecutionRuntime
    cases: tuple[ExecutionCase, ...]
    schema_version: int = EXECUTION_PLAN_SCHEMA_VERSION

    @property
    def batteries(self) -> tuple[ExecutionCase, ...]:
        return self.cases

    @property
    def duckdb_version(self) -> str:
        return self.runtime.duckdb_version

    @property
    def ci_tools_version(self) -> str:
        return self.runtime.ci_tools_version

    def payload(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "runtime": self.runtime.payload(),
            "cases": [case.payload() for case in self.cases],
        }

    def matrix(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "include": [
                case.matrix_payload(self.runtime.duckdb_version) for case in self.cases
            ]
        }

    def canonical_json(self) -> str:
        return json.dumps(self.payload(), separators=(",", ":"), sort_keys=True)

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.payload(), indent=2) + "\n", encoding="utf-8")

    def github_outputs(self) -> tuple[str, ...]:
        compact_matrix = json.dumps(self.matrix(), separators=(",", ":"))
        enabled = ",".join(case.name for case in self.cases)
        return (
            f"matrix={compact_matrix}",
            f"duckdb_version={self.runtime.duckdb_version}",
            f"ci_tools_version={self.runtime.ci_tools_version}",
            f"enabled_batteries={enabled}",
            f"execution_plan_sha256={self.sha256()}",
        )
