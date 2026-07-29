"""Versioned execution plan emitted by the DuckDB extension QA compiler."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXECUTION_PLAN_SCHEMA_VERSION = 4


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
    name: str
    service_type: str
    options: tuple[tuple[str, Any], ...] = ()

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {"name": self.name, "type": self.service_type}
        result.update(dict(self.options))
        return result


@dataclass(frozen=True, slots=True)
class ExecutionPrerequisite:
    prerequisite_type: str

    def payload(self) -> dict[str, str]:
        return {"type": self.prerequisite_type}


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
    capabilities: tuple[str, ...]
    profiles: tuple[ExecutionProfile, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "runner": self.runner,
            "services": [service.payload() for service in self.services],
            "prerequisites": [item.payload() for item in self.prerequisites],
            "capabilities": list(self.capabilities),
            "profiles": [profile.payload() for profile in self.profiles],
        }


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
        profiles = [profile.payload() for profile in self.contract.profiles]
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
            "capabilities": list(self.contract.capabilities),
            "profiles": profiles,
            "extensions": [extension.payload() for extension in self.extensions],
            "ignoredTests": [ignored.payload() for ignored in self.ignored_tests],
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
