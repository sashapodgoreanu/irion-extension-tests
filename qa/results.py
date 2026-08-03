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
    """Parse and aggregate DuckDB SQLLogicTest/Catch summaries."""
    discovered_values = [int(value) for value in _PROGRESS_RE.findall(text)]
    discovered = max(discovered_values) if discovered_values else None

    passed_matches = _PASS_RE.findall(text)
    all_skipped_matches = _ALL_SKIPPED_RE.findall(text)
    cases_matches = _CASES_RE.findall(text)
    assertions_matches = _ASSERTIONS_RE.findall(text)

    if passed_matches or all_skipped_matches or cases_matches:
        passed_executed = sum(int(match[2]) for match in passed_matches)
        passed_skipped = sum(int(match[0] or 0) for match in passed_matches)
        catch_executed = sum(int(match[0]) for match in cases_matches)
        catch_passed = sum(int(match[1]) for match in cases_matches)
        catch_failed = sum(int(match[2]) for match in cases_matches)
        catch_skipped = sum(int(match[3] or 0) for match in cases_matches)
        entirely_skipped = sum(int(value) for value in all_skipped_matches)

        executed = passed_executed + catch_executed
        skipped = passed_skipped + catch_skipped + entirely_skipped
        assertions = sum(int(match[1]) for match in passed_matches)
        assertions += sum(int(match[0]) for match in assertions_matches)

        return {
            "summaryFound": True,
            "discovered": discovered if discovered is not None else executed + skipped,
            "executed": executed,
            "passed": passed_executed + catch_passed,
            "failed": catch_failed,
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


def _profile_logs(
    log_dir: Path, profile_name: str, profile_count: int
) -> list[Path]:
    exact = log_dir / f"unittest-{profile_name}.log"
    if exact.is_file():
        return [exact]

    composite = sorted(
        path
        for path in log_dir.glob(f"unittest-{profile_name}-*.log")
        if path.is_file()
    )
    if composite:
        return composite

    if profile_count == 1:
        legacy = log_dir / "unittest.log"
        if legacy.is_file():
            return [legacy]
    return []


def _combine_unittest_summaries(
    parsed_logs: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics = ("discovered", "executed", "passed", "failed", "skipped", "assertions")
    result: dict[str, Any] = {
        "summaryFound": bool(parsed_logs)
        and all(item["summaryFound"] for item in parsed_logs)
    }
    for metric in metrics:
        values = [item[metric] for item in parsed_logs]
        result[metric] = (
            sum(int(value) for value in values)
            if values and all(value is not None for value in values)
            else None
        )
    return result


def _profile_irion_exclusions(
    battery: dict[str, Any], profile_name: str
) -> list[dict[str, str]]:
    exclusions: list[dict[str, str]] = []
    for ignored in battery.get("ignoredTests", []):
        profiles = ignored.get("profiles", [])
        if profiles and profile_name not in profiles:
            continue
        exclusions.append(
            {
                "path": str(ignored["path"]),
                "reason": str(ignored["reason"]),
            }
        )
    return exclusions


def _not_executed(parsed: dict[str, Any]) -> int | None:
    discovered = parsed.get("discovered")
    executed = parsed.get("executed")
    if discovered is None or executed is None:
        return None
    return max(0, int(discovered) - int(executed))


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
        log_paths = _profile_logs(log_dir, name, len(profiles_config))
        if not log_paths:
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
            parsed_logs = [
                parse_unittest_log(
                    path.read_text(encoding="utf-8", errors="replace")
                )
                for path in log_paths
            ]
            parsed = _combine_unittest_summaries(parsed_logs)
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
            log_name = ",".join(path.name for path in log_paths)

        profiles.append(
            {
                "name": name,
                "filter": profile.get("tests"),
                "status": profile_status,
                "log": log_name,
                **parsed,
                "notExecuted": _not_executed(parsed),
                "irionExclusions": _profile_irion_exclusions(battery, name),
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

    runtime = battery.get("runtime")
    if not isinstance(runtime, dict):
        runtime = {
            "duckdbVersion": battery.get("duckdbVersion"),
            "ciToolsVersion": None,
            "operatingSystem": None,
            "architecture": None,
            "githubRunner": None,
        }

    prerequisites = [
        str(item["type"])
        for item in battery.get("prerequisites", [])
        if isinstance(item, dict) and item.get("type")
    ]
    external_not_run = bool(
        status == "accepted_failure" and has_not_run and prerequisites
    )

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
        "runtime": runtime,
        "upstream": {
            "type": battery.get("sourceType", "remote"),
            "repository": battery.get("repository"),
            "pin": battery.get("pin"),
            "commit": test_info.get("upstream_commit"),
        },
        "externalPrerequisite": {
            "notRun": external_not_run,
            "reason": reason if external_not_run else None,
            "prerequisites": prerequisites if external_not_run else [],
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


def _skip_authorizations(
    policy: dict[str, Any] | None, case_id: str, profile_name: str
) -> list[dict[str, Any]]:
    if policy is None:
        return []
    return [
        item
        for item in policy.get("skipAuthorizations", [])
        if item.get("case") == case_id and item.get("profile") == profile_name
    ]


def classify_non_execution(
    result: dict[str, Any], policy: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    classifications: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    case_id = str(result.get("caseId", ""))
    external = result.get("externalPrerequisite") or {}

    for profile in result.get("profiles", []):
        profile_name = str(profile.get("name", ""))
        observed = profile.get("notExecuted")
        authorizations = _skip_authorizations(policy, case_id, profile_name)
        expected = 0
        reason: str | None = None
        if len(authorizations) == 1:
            expected = int(authorizations[0]["expected"])
            reason = str(authorizations[0]["reason"])
        elif len(authorizations) > 1:
            violations.append(
                {
                    "caseId": case_id,
                    "profile": profile_name,
                    "type": "duplicate_authorization",
                    "observed": observed,
                    "expected": None,
                }
            )

        is_external = bool(
            external.get("notRun") and profile.get("status") == "not_run"
        )
        unexpected: int | None
        authorization_shortfall: int | None
        if is_external:
            unexpected = None
            authorization_shortfall = None
        elif observed is None:
            unexpected = None
            authorization_shortfall = None
            violations.append(
                {
                    "caseId": case_id,
                    "profile": profile_name,
                    "type": "missing_metrics",
                    "observed": None,
                    "expected": expected,
                }
            )
        else:
            unexpected = max(0, int(observed) - expected)
            authorization_shortfall = max(0, expected - int(observed))
            if unexpected:
                violations.append(
                    {
                        "caseId": case_id,
                        "profile": profile_name,
                        "type": "unexpected_skip",
                        "observed": int(observed),
                        "expected": expected,
                    }
                )
            if authorization_shortfall:
                violations.append(
                    {
                        "caseId": case_id,
                        "profile": profile_name,
                        "type": "stale_authorization",
                        "observed": int(observed),
                        "expected": expected,
                    }
                )

        classifications.append(
            {
                "caseId": case_id,
                "profile": profile_name,
                "observedNotExecuted": observed,
                "runnerReportedSkipped": profile.get("skipped"),
                "upstreamDeclared": expected,
                "upstreamReason": reason,
                "irionExclusions": list(profile.get("irionExclusions", [])),
                "externalPrerequisite": is_external,
                "externalReason": external.get("reason") if is_external else None,
                "unexpected": unexpected,
                "authorizationShortfall": authorization_shortfall,
            }
        )

    return classifications, violations


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
    non_execution: list[dict[str, Any]] = []
    skip_violations: list[dict[str, Any]] = []
    external_prerequisite_cases: list[str] = []

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

        classifications, case_skip_violations = classify_non_execution(result, policy)
        non_execution.extend(classifications)
        skip_violations.extend(case_skip_violations)
        if (result.get("externalPrerequisite") or {}).get("notRun"):
            external_prerequisite_cases.append(case_id)

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
    if (
        missing
        or unexpected
        or duplicate_cases
        or invalid
        or failed
        or coverage
        or skip_violations
    ):
        verdict = "failed"

    return {
        "schemaVersion": SUMMARY_SCHEMA_VERSION,
        "status": verdict,
        "generatedAt": utc_now(),
        "runtime": plan.get("runtime"),
        "expectedCases": sorted(cases),
        "passedCases": passed,
        "acceptedFailureCases": accepted_failures,
        "externalPrerequisiteCases": sorted(set(external_prerequisite_cases)),
        "failedCases": failed,
        "invalidCases": sorted(set(invalid)),
        "missingCases": missing,
        "unexpectedCases": unexpected,
        "duplicateCases": sorted(set(duplicate_cases)),
        "coverageViolations": coverage,
        "nonExecution": non_execution,
        "skipViolations": skip_violations,
        "results": [
            by_case[name] for name in sorted(by_case) if name in cases
        ],
    }


def summary_markdown(summary: dict[str, Any]) -> str:
    runtime = summary.get("runtime") or {}
    runtime_text = (
        f"{runtime.get('operatingSystem', 'unknown')}/"
        f"{runtime.get('architecture', 'unknown')} on "
        f"{runtime.get('githubRunner', 'unknown')}"
    )
    lines = [
        "# DuckDB extension QA summary",
        "",
        f"**Verdict:** `{summary['status']}`",
        "",
        f"**Runtime:** `{runtime_text}`",
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
        ("External prerequisites not available", "externalPrerequisiteCases"),
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

    non_execution = summary.get("nonExecution", [])
    if non_execution:
        lines.extend(
            [
                "",
                "## Non-execution classification",
                "",
                "| Case | Profile | Observed | Upstream declared | Irion exclusions | External prerequisite | Unexpected |",
                "|---|---|---:|---:|---:|---|---:|",
            ]
        )
        for item in non_execution:
            external_text = "yes" if item["externalPrerequisite"] else "no"
            lines.append(
                f"| `{item['caseId']}` | `{item['profile']}` | "
                f"{item['observedNotExecuted']} | {item['upstreamDeclared']} | "
                f"{len(item['irionExclusions'])} | {external_text} | "
                f"{item['unexpected']} |"
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

    skip_violations = summary.get("skipViolations", [])
    if skip_violations:
        lines.extend(
            [
                "",
                "## Skip policy violations",
                "",
                "| Case | Profile | Type | Observed | Authorized |",
                "|---|---|---|---:|---:|",
            ]
        )
        for violation in skip_violations:
            lines.append(
                f"| `{violation['caseId']}` | `{violation['profile']}` | "
                f"{violation['type']} | {violation['observed']} | "
                f"{violation['expected']} |"
            )
    return "\n".join(lines) + "\n"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value
