#!/usr/bin/env python3
"""Fail when SQLLogicTest skips requirements that the selected QA profile needs."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REQUIRE_LINE = re.compile(r"^require\s+([^:]+):\s+([1-9][0-9]*)$")
REQUIRE_ENV_LINE = re.compile(r"^require-env\s+([^:]+):\s+([1-9][0-9]*)$", re.IGNORECASE)
AZURE_CLOUD_REQUIRED_ENV = {
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "AZURE_AUTH_ENV",
}


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} UNITTEST_LOG EXTENSIONS_JSON", file=sys.stderr)
        return 2

    log_path = Path(sys.argv[1])
    selected = {
        item["name"]
        for item in json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    }
    skipped_extensions: list[tuple[str, int]] = []
    skipped_cloud_env: list[tuple[str, int]] = []

    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        match = REQUIRE_LINE.fullmatch(stripped)
        if match and match.group(1) in selected:
            skipped_extensions.append((match.group(1), int(match.group(2))))

        # The upstream Azure suite normally treats missing environment variables
        # as a skipped SQLLogicTest. For our cloud compatibility profile the
        # Service Principal environment is mandatory: missing credentials must
        # make the battery fail rather than silently reduce cloud coverage.
        if log_path.name == "unittest-cloud.log":
            env_match = REQUIRE_ENV_LINE.fullmatch(stripped)
            if env_match and env_match.group(1) in AZURE_CLOUD_REQUIRED_ENV:
                skipped_cloud_env.append((env_match.group(1), int(env_match.group(2))))

    if skipped_extensions:
        for name, count in skipped_extensions:
            print(f"Required configured extension was skipped: {name} ({count})", file=sys.stderr)

    if skipped_cloud_env:
        for name, count in skipped_cloud_env:
            print(
                f"Required Azure cloud environment was skipped instead of executed: {name} ({count})",
                file=sys.stderr,
            )

    return 1 if skipped_extensions or skipped_cloud_env else 0


if __name__ == "__main__":
    raise SystemExit(main())
