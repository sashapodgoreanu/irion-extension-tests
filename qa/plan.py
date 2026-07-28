"""Versioned execution plan emitted by the DuckDB extension QA compiler."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXECUTION_PLAN_SCHEMA_VERSION = 1


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
class ExecutionContract:
    runner: str
    setup: str
    tests: str

    def payload(self) -> dict[str, str]:
        return {
            "runner": self.runner,
            "setup": self.setup,
            "tests": self.tests,
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
        """Preserve the phase-1 GitHub Actions matrix contract exactly."""

        return {
            "name": self.name,
            "runner": self.contract.runner,
            "repository": self.source.repository,
            "pin": self.source.pin,
            "tests": self.contract.tests,
            "submodules": self.source.submodules,
            "setup": self.contract.setup,
            "duckdbVersion": duckdb_version,
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
        """Backward-compatible name used by phase-1 callers and tests."""

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
