#!/usr/bin/env python3
"""Validate and aggregate all matrix result artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from jsonschema import Draft202012Validator

from qa.results import aggregate_results, find_result_files, load_json, summary_markdown


def validate(instance: dict, schema_path: Path, label: str) -> None:
    schema = load_json(schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda item: list(item.path),
    )
    if errors:
        details = "; ".join(error.message for error in errors[:10])
        raise ValueError(f"Invalid {label}: {details}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--result-schema", type=Path, required=True)
    parser.add_argument("--summary-schema", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()

    plan = load_json(args.plan)
    result_files = find_result_files(args.results_root)
    results: list[dict] = []
    invalid_files: list[str] = []
    for path in result_files:
        try:
            result = load_json(path)
            validate(result, args.result_schema, str(path))
            results.append(result)
        except (ValueError, json.JSONDecodeError) as exc:
            invalid_files.append(f"{path}: {exc}")

    summary = aggregate_results(plan, results)
    if invalid_files:
        summary["status"] = "failed"
        summary["invalidResultFiles"] = invalid_files
    validate(summary, args.summary_schema, "aggregate summary")

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    args.output_markdown.write_text(summary_markdown(summary), encoding="utf-8")
    print(args.output_markdown.read_text(encoding="utf-8"))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
