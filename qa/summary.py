"""Human-readable Markdown summary for DuckDB extension QA results."""

from __future__ import annotations

from typing import Any


def _metric(value: Any) -> str:
    return "—" if value is None else str(value)


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
        "## Test results",
        "",
        "| Case | Profile | Total tests | OK tests | KO tests | Skipped tests |",
        "|---|---|---:|---:|---:|---:|",
    ]

    by_case = {
        result["caseId"]: result for result in summary.get("results", [])
    }
    for case_id in summary.get("expectedCases", []):
        result = by_case.get(case_id)
        if result is None:
            lines.append(f"| `{case_id}` | — | — | — | — | — |")
            continue

        profiles = result.get("profiles", [])
        if not profiles:
            lines.append(f"| `{case_id}` | — | — | — | — | — |")
            continue

        for profile in profiles:
            lines.append(
                f"| `{case_id}` | `{profile['name']}` | "
                f"{_metric(profile.get('discovered'))} | "
                f"{_metric(profile.get('passed'))} | "
                f"{_metric(profile.get('failed'))} | "
                f"{_metric(profile.get('skipped'))} |"
            )

    lines.extend(
        [
            "",
            "Skipped test details are available in the logs and structured result of each battery.",
        ]
    )

    for title, key in (
        ("Accepted failures", "acceptedFailureCases"),
        ("External prerequisites not available", "externalPrerequisiteCases"),
        ("Failed", "failedCases"),
        ("Invalid", "invalidCases"),
        ("Missing", "missingCases"),
        ("Unexpected cases", "unexpectedCases"),
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

    coverage_violations = summary.get("coverageViolations", [])
    if coverage_violations:
        lines.extend(
            [
                "",
                "## Coverage violations",
                "",
                "| Case | Profile | Metric | Actual | Required |",
                "|---|---|---|---:|---:|",
            ]
        )
        for violation in coverage_violations:
            lines.append(
                f"| `{violation['caseId']}` | `{violation['profile']}` | "
                f"{violation['metric']} | {_metric(violation['actual'])} | "
                f"{violation['operator']} {violation['expected']} |"
            )

    skip_violations = summary.get("skipViolations", [])
    if skip_violations:
        lines.extend(
            [
                "",
                "## Skip policy violations",
                "",
                "| Case | Profile | Type | Skipped tests | Authorized skips |",
                "|---|---|---|---:|---:|",
            ]
        )
        for violation in skip_violations:
            lines.append(
                f"| `{violation['caseId']}` | `{violation['profile']}` | "
                f"{violation['type']} | {_metric(violation['observed'])} | "
                f"{_metric(violation['expected'])} |"
            )

    return "\n".join(lines) + "\n"
