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
        "Skipped/non-executed counts are informational and do not affect the verdict.",
        "",
        "## Test results",
        "",
        "| Case | Profile | OK tests | KO tests | Skipped / not executed |",
        "|---|---|---:|---:|---:|",
    ]

    by_case = {
        result["caseId"]: result for result in summary.get("results", [])
    }
    for case_id in summary.get("expectedCases", []):
        result = by_case.get(case_id)
        if result is None:
            lines.append(f"| `{case_id}` | — | — | — | — |")
            continue

        profiles = result.get("profiles", [])
        if not profiles:
            lines.append(f"| `{case_id}` | — | — | — | — |")
            continue

        for profile in profiles:
            skipped = profile.get("skipped")
            if skipped is None:
                skipped = profile.get("notExecuted")
            lines.append(
                f"| `{case_id}` | `{profile['name']}` | "
                f"{_metric(profile.get('passed'))} | "
                f"{_metric(profile.get('failed'))} | "
                f"{_metric(skipped)} |"
            )

    for title, key in (
        ("Accepted failures", "acceptedFailureCases"),
        ("External prerequisites not available", "externalPrerequisiteCases"),
        ("Failed", "failedCases"),
        ("Invalid", "invalidCases"),
        ("Missing", "missingCases"),
        ("Unexpected cases", "unexpectedCases"),
        ("Duplicate results", "duplicateCases"),
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

    return "\n".join(lines) + "\n"
