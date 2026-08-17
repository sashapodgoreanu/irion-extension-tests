#!/usr/bin/env python3
"""Write or preserve one structured test result."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from qa.results import build_case_result, load_json, result_exit_code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--battery-config", type=Path, required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--started-at-ms", type=int, default=0)
    parser.add_argument("--reason")
    parser.add_argument(
        "--preserve-existing",
        action="store_true",
        help=(
            "Finalize reporting without propagating the logical test verdict. "
            "Preserve an existing structured result when present; otherwise "
            "write one from the supplied execution evidence."
        ),
    )
    args = parser.parse_args()

    if args.preserve_existing and args.output.is_file():
        result = load_json(args.output)
        print(
            f"Preserving structured result: {args.output} "
            f"({result.get('status', '<unknown>')})"
        )
        # Reporting/finalization must remain runnable after a failed battery.
        # The failure is represented inside result.json and enforced later by
        # aggregation; it must not make the reporting step itself fail.
        return 0

    battery = load_json(args.battery_config)
    result = build_case_result(
        battery,
        args.log_dir,
        exit_code=args.exit_code,
        started_at_ms=args.started_at_ms,
        reason=args.reason,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Structured result: {args.output} ({result['status']})")

    if args.preserve_existing:
        # `--preserve-existing` is used by the always() finalization steps in
        # GitHub Actions. A valid failed result is successful reporting, not a
        # writer failure. Keep the verdict in JSON for the aggregate gate.
        return 0
    return result_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
