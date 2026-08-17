#!/usr/bin/env python3
"""Validate and aggregate all matrix result artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from qa.results import aggregate_results, find_result_files, load_json
from qa.summary import summary_markdown


def validate(instance: dict, schema_path: Path, label: str) -> None:
    schema = load_json(schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda item: list(item.path),
    )
    if errors:
        details = "; ".join(error.message for error in errors[:10])
        raise ValueError(f"Invalid {label}: {details}")


def select_runtime_plan(plan_path: Path, base_plan: dict, results: list[dict]) -> dict:
    """Select the generated runner plan matching the structured results runtime."""
    operating_systems = {
        str((result.get("runtime") or {}).get("operatingSystem", "")).strip()
        for result in results
        if str((result.get("runtime") or {}).get("operatingSystem", "")).strip()
    }
    if not operating_systems:
        return base_plan
    if len(operating_systems) != 1:
        raise ValueError(
            "Cannot aggregate results from multiple operating systems: "
            + ", ".join(sorted(operating_systems))
        )

    operating_system = next(iter(operating_systems))
    candidates = sorted(
        plan_path.parent.glob(f"{plan_path.stem}-*{plan_path.suffix}")
    )
    for candidate in candidates:
        candidate_plan = load_json(candidate)
        candidate_runtime = candidate_plan.get("runtime") or {}
        if candidate_runtime.get("operatingSystem") == operating_system:
            print(
                f"Using runtime-specific execution plan {candidate} "
                f"for operatingSystem={operating_system}"
            )
            return candidate_plan

    base_runtime = base_plan.get("runtime") or {}
    if base_runtime.get("operatingSystem") != operating_system:
        raise ValueError(
            f"No execution plan found for operatingSystem={operating_system}; "
            f"base plan runtime is {base_runtime.get('operatingSystem')!r}"
        )
    return base_plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--result-schema", type=Path, required=True)
    parser.add_argument("--summary-schema", type=Path, required=True)
    # Deprecated compatibility options. They are intentionally ignored:
    # numeric test-count/skip policies no longer influence the verdict.
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--policy-schema", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()

    base_plan = load_json(args.plan)

    result_files = find_result_files(args.results_root)
    print(
        f"Discovered {len(result_files)} structured result file(s) "
        f"under {args.results_root}"
    )
    results: list[dict] = []
    invalid_files: list[str] = []
    for path in result_files:
        try:
            result = load_json(path)
            validate(result, args.result_schema, str(path))
            results.append(result)
        except (ValueError, json.JSONDecodeError) as exc:
            message = f"{path}: {exc}"
            invalid_files.append(message)
            print(f"Invalid structured result: {message}", file=sys.stderr)

    plan = select_runtime_plan(args.plan, base_plan, results)
    summary = aggregate_results(plan, results)
    if invalid_files:
        summary["status"] = "failed"
        summary["invalidResultFiles"] = invalid_files
    validate(summary, args.summary_schema, "aggregate summary")

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    args.output_markdown.write_text(summary_markdown(summary), encoding="utf-8")
    print(args.output_markdown.read_text(encoding="utf-8"))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
