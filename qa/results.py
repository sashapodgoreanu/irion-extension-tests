"""Structured QA result generation, coverage checks and aggregation."""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

RESULT_SCHEMA_VERSION = 1
SUMMARY_SCHEMA_VERSION = 1

_PROGRESS_RE = re.compile(r"\[(?:\d+)/(\d+)\]")
_PASS_RE = re.compile(
    r"All tests passed \((?:(\d+) skipped tests?, )?(\d+) assertions? in (\d+) test cases?\)"
)
_ALL_SKIPPED_RE = re.compile(
    r"All tests were skipped \(total skipped (\d+)\)", re.IGNORECASE
)
_CASES_RE = re.compile(
    r"test cases:\s*(\d+)\s*\|\s*(\d+) passed\s*\|\s*(\d+) failed(?:\s*\|\s*(\d+) skipped)?",
    re.IGNORECASE,
)
_ASSERTIONS_RE = re.compile(
    r"assertions:\s*(\d+)\s*\|\s*(\d+) passed\s*\|\s*(\d+) failed(?:\s*\|\s*(\d+) skipped)?",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_unittest_log(text: str) -> dict[str, Any]:
    """Parse DuckDB SQLLogicTest/Catch summaries across runner versions."""
    discovered_values = [int(value) for value in _PROGRESS_RE.findall(text)]
    discovered = max(discovered_values) if discovered_values else None

    passed_match = _PASS_RE.search(text)
    if passed_match:
        skipped = int(passed_match.group(1) or 0)
        assertions = int(passed_match.group(2))
        executed = int(passed_match.group(3))
        return {
            "summaryFound": True,
            "discovered": discovered if discovered is not None else executed + skipped,
            "executed": executed,
            "passed": executed,
            "failed": 0,
            "skipped": skipped,
            "assertions": assertions,
        }

    skipped_match = _ALL_SKIPPED_RE.search(text)
    if skipped_match:
        skipped = int(skipped_match.group(1))
        return {
            "summaryFound": True,
            "discovered": discovered if discovered is not None else skipped,
            "executed": 0,
            "passed": 0,
            "failed": 0,
            "skipped": skipped,
            "assertions": 0,
        }

    cases_match = _CASES_RE.search(text)
    if cases_match:
        executed = int(cases_match.group(1))
        passed = int(cases_match.group(2))
        failed = int(cases_match.group(3))
        skipped = int(cases_match.group(4) or 0)
        assertions_match = _ASSERTIONS_RE.search(text)
        assertions = int(assertions_match.group(1)) if assertions_match else None
        return {
            "summaryFound": True,
            "discovered": discovered if discovered is not None else executed,
            "executed": executed,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "assertions": assertions,
        }

    return {
        "summaryFound": False,
        "discovered": discovered,
        "executed": None,
        "passed": None,
        "failed": None,
        "skipped": None,
        "assertions": None,
    }


def _read_key_values(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _bool(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    return value.strip().lower() in {"1", "true", "yes"}


def _extension_states(
    log_dir: Path, expected: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    csv_path = log_dir / "extensions.csv"
    expected_names = [str(item["name"]) for item in expected]
    by_name: dict[str, dict[str, str]] = {}
    if csv_path.is_file():
        with csv_path.open(encoding="utf-8", newline="") as handle:
            by_name = {
                row.get("extension_name", ""): row
                for row in csv.DictReader(handle)
            }

    result: list[dict[str, Any]] = []
    for name in expected_names:
        row = by_name.get(name, {})
        result.append(
            {
                "name": name,
                "installed": _bool(row.get("installed")),
                "loaded": _bool(row.get("loaded")),
                "version": row.get("extension_version") or None,
                "installMode": row.get("install_mode") or None,
                "installedFrom": row.get("installed_from") or None,
            }
        )
    return result


def _profile_log(
    log_dir: Path, profile_name: str, profile_count: int
) -> Path | None:
    candidates = [log_dir / f"unittest-{profile_name}.log"]
    if profile_count == 1:
        candidates.append(log_dir / "unittest.log")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def build_case_result(
    battery: dict[str, Any],
    log_dir: Path,
    *,
    exit_code: int,
    started_at_ms: int | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    finished_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if started_at_ms is None or started_at_ms <= 0:
        started_at_ms = finished_ms
    accepted = "accepted-failure" in battery.get("capabilities", [])
    profiles_config = list(battery.get("profiles", []))
    profiles: list[dict[str, Any]] = []

    for profile in profiles_config:
        name = str(profile["name"])
        log_path = _profile_log(log_dir, name, len(profiles_config))
        if log_path is None:
            parsed = {
                "summaryFound": False,
                "discovered": None,
                "executed": None,
                "passed": None,
                "failed": None,
                "skipped": None,
                "assertions": None,
            }
            profile_status = "not_run"
            log_name = None
        else:
            parsed = parse_unittest_log(
                log_path.read_text(encoding="utf-8", errors="replace")
            )
            failed = parsed["failed"]
            executed = parsed["executed"]
            skipped = parsed["skipped"]
            if not parsed["summaryFound"]:
                profile_status = "invalid"
            elif failed and failed > 0:
                profile_status = "failed"
            elif executed == 0 and skipped and skipped > 0:
                profile_status = "skipped"
            else:
                profile_status = "passed"
            log_name = log_path.name

        profiles.append(
            {
                "name": name,
                "filter": profile.get("tests"),
                "status": profile_status,
                "log": log_name,
                **parsed,
            }
        )

    has_profile_failure = any(
        item["status"] in {"failed", "invalid"} for item in profiles
    )
    has_not_run = any(item["status"] == "not_run" for item in profiles)
    raw_failed = exit_code != 0 or has_profile_failure or has_not_run or bool(reason)
    status = (
        "accepted_failure"
        if raw_failed and accepted
        else "failed"
        if raw_failed
        else "passed"
    )

    test_info = _read_key_values(log_dir / "test-info.txt")
    declared_services = list(battery.get("services", []))
    for profile in profiles_config:
        for service in profile.get("services", []):
            declared_services.append({"profile": profile["name"], **service})

    return {
        "schemaVersion": RESULT_SCHEMA_VERSION,
        "caseId": str(battery["name"]),
        "battery": str(battery["name"]),
        "runner": str(battery["runner"]),
        "status": status,
        "acceptedFailure": accepted,
        "exitCode": int(exit_code),
        "reason": reason,
        "startedAt": datetime.fromtimestamp(
            started_at_ms / 1000, timezone.utc
        )
        .isoformat()
        .replace("+00:00", "Z"),
        "finishedAt": utc_now(),
        "durationMs": max(0, finished_ms - started_at_ms),
        "duckdbVersion": battery.get("duckdbVersion"),
        "upstream": {
            "repository": battery.get("repository"),
            "pin": battery.get("pin"),
            "commit": test_info.get("upstream_commit"),
        },
        "profiles": profiles,
        "extensions": _extension_states(
            log_dir, battery.get("extensions", [])
        ),
        "services": declared_services,
    }


def result_exit_code(result: dict[str, Any]) -> int:
    return 0 if result.get("status") in {"passed", "accepted_failure"} else 1


def find_result_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("result.json") if path.is_file()
    )


def coverage_thresholds(
    policy: dict[str, Any] | None, case_id: str, profile_name: str
) -> dict[str, int]:
    if policy is None:
        return {}
    thresholds = {
        key: int(value)
        for key, value in policy.get("defaults", {}).items()
    }
    for override in policy.get("overrides", []):
        if override.get("case") != case_id:
            continue
        selected_profile = override.get("profile")
        if selected_profile is not None and selected_profile != profile_name:
            continue
        for key in ("minimumDiscovered", "minimumExecuted", "maximumSkipped"):
            if key in override:
                thresholds[key] = int(override[key])
    return thresholds


def coverage_violations(
    result: dict[str, Any], policy: dict[str, Any] | None
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    case_id = str(result.get("caseId", ""))
    for profile in result.get("profiles", []):
        profile_name = str(profile.get("name", ""))
        thresholds = coverage_thresholds(policy, case_id, profile_name)
        checks = (
            ("minimumDiscovered", "discovered", ">="),
            ("minimumExecuted", "executed", ">="),
            ("maximumSkipped", "skipped", "<="),
        )
        for threshold_name, metric, operator in checks:
            if threshold_name not in thresholds:
                continue
            actual = profile.get(metric)
            expected = thresholds[threshold_name]
            failed = actual is None
            if actual is not None:
                failed = actual < expected if operator == ">=" else actual > expected
            if failed:
                violations.append(
                    {
                        "caseId": case_id,
                        "profile": profile_name,
                        "metric": metric,
                        "operator": operator,
                        "actual": actual,
                        "expected": expected,
                    }
                )
    return violations


def aggregate_results(
    plan: dict[str, Any],
    results: list[dict[str, Any]],
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cases = {str(case["name"]): case for case in plan.get("cases", [])}
    by_case: dict[str, dict[str, Any]] = {}
    duplicate_cases: list[str] = []
    for result in results:
        case_id = str(result.get("caseId", ""))
        if case_id in by_case:
            duplicate_cases.append(case_id)
        by_case[case_id] = result

    missing = sorted(set(cases) - set(by_case))
    unexpected = sorted(set(by_case) - set(cases))
    invalid: list[str] = []
    failed: list[str] = []
    accepted_failures: list[str] = []
    passed: list[str] = []
    coverage: list[dict[str, Any]] = []

    for case_id, result in sorted(by_case.items()):
        if case_id not in cases:
            continue
        expected_accepted = "accepted-failure" in cases[case_id][
            "execution"
        ].get("capabilities", [])
        status = result.get("status")
        if bool(result.get("acceptedFailure")) != expected_accepted:
            invalid.append(case_id)
            continue
        if status == "passed":
            if any(
                profile.get("status")
                not in {"passed", "skipped"}
                for profile in result.get("profiles", [])
            ):
                invalid.append(case_id)
            else:
                passed.append(case_id)
                coverage.extend(coverage_violations(result, policy))
        elif status == "accepted_failure" and expected_accepted:
            accepted_failures.append(case_id)
        elif status == "failed":
            failed.append(case_id)
        else:
            invalid.append(case_id)

    verdict = "passed"
    if missing or unexpected or duplicate_cases or invalid or failed or coverage:
        verdict = "failed"

    return {
        "schemaVersion": SUMMARY_SCHEMA_VERSION,
        "status": verdict,
        "generatedAt": utc_now(),
        "expectedCases": sorted(cases),
        "passedCases": passed,
        "acceptedFailureCases": accepted_failures,
        "failedCases": failed,
        "invalidCases": sorted(set(invalid)),
        "missingCases": missing,
        "unexpectedCases": unexpected,
        "duplicateCases": sorted(set(duplicate_cases)),
        "coverageViolations": coverage,
        "results": [
            by_case[name] for name in sorted(by_case) if name in cases
        ],
    }


def summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# DuckDB extension QA summary",
        "",
        f"**Verdict:** `{summary['status']}`",
        "",
        "| Case | Status | Profiles |",
        "|---|---|---|",
    ]
    by_case = {
        result["caseId"]: result for result in summary.get("results", [])
    }
    for case_id in summary.get("expectedCases", []):
        result = by_case.get(case_id)
        if result is None:
            lines.append(f"| `{case_id}` | missing | — |")
            continue
        profiles = ", ".join(
            f"{item['name']}={item['status']}"
            for item in result.get("profiles", [])
        ) or "—"
        lines.append(
            f"| `{case_id}` | {result['status']} | {profiles} |"
        )

    for title, key in (
        ("Accepted failures", "acceptedFailureCases"),
        ("Failed", "failedCases"),
        ("Invalid", "invalidCases"),
        ("Missing", "missingCases"),
        ("Unexpected", "unexpectedCases"),
    ):
        values = summary.get(key, [])
        if values:
            lines.extend(
                [
                    "",
                    f"## {title}",
                    "",
                    ", ".join(f"`{value}`" for value in values),
                ]
            )

    violations = summary.get("coverageViolations", [])
    if violations:
        lines.extend(
            [
                "",
                "## Coverage violations",
                "",
                "| Case | Profile | Metric | Actual | Required |",
                "|---|---|---|---:|---:|",
            ]
        )
        for violation in violations:
            lines.append(
                f"| `{violation['caseId']}` | `{violation['profile']}` | "
                f"{violation['metric']} | {violation['actual']} | "
                f"{violation['operator']} {violation['expected']} |"
            )
    return "\n".join(lines) + "\n"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value
