#!/usr/bin/env python3
"""Apply a minimal, pinned Docker image fix to the DuckDB Iceberg test fixture.

The upstream Iceberg commit used by our QA suite names two removed Docker Hub
image repositories. Only replace their original, unversioned image references;
fail if the upstream fixture drifts rather than silently patching arbitrary files.
This adaptation applies in both Linux and native-Windows/WSL fixture builds.
"""

from __future__ import annotations

import sys
from pathlib import Path

IMAGE_REPLACEMENTS = (
    ("minio/minio", "dappros/minio:RELEASE.2025-09-07T16-13-09Z"),
    ("minio/mc", "ghcr.io/golithus/mc:RELEASE.2025-08-13T08-35-41Z"),
)


def patch_iceberg_fixture(upstream_root: Path) -> bool:
    compose = upstream_root / "scripts" / "docker-compose.yml"
    original = compose.read_text(encoding="utf-8")
    updated = original

    for old_image, replacement_image in IMAGE_REPLACEMENTS:
        old_line = f"    image: {old_image}\n"
        replacement_line = f"    image: {replacement_image}\n"
        if updated.count(old_line) == 1:
            updated = updated.replace(old_line, replacement_line, 1)
        elif updated.count(replacement_line) == 1:
            # Be idempotent for local reruns on the same checkout.
            continue
        else:
            raise ValueError(
                f"Unexpected Iceberg fixture image for {old_image}: "
                "review upstream docker-compose.yml before changing the mapping"
            )

    if updated != original:
        compose.write_text(updated, encoding="utf-8")
        return True
    return False


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: patch-iceberg-fixture.py <upstream-root>", file=sys.stderr)
        return 2
    try:
        changed = patch_iceberg_fixture(Path(sys.argv[1]))
    except (OSError, ValueError) as exc:
        print(f"Unable to adapt Iceberg Docker fixtures: {exc}", file=sys.stderr)
        return 1
    print(f"Iceberg MinIO fixture ready; changed={str(changed).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
