#!/usr/bin/env python3
from __future__ import annotations

import base64
import gzip
import json
import subprocess
from pathlib import Path

root = Path.cwd()
payload = "".join(
    (root / ".phase4" / f"chunk-{index:02d}").read_text(encoding="utf-8")
    for index in range(7)
)
archive = json.loads(gzip.decompress(base64.b64decode(payload)))
for relative, item in archive.items():
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.decompress(base64.b64decode(item["data"])))
    path.chmod(item["mode"])

for relative in (
    ".github/workflows/apply-phase4.yml",
    "scripts/apply-phase4-payload.py",
):
    (root / relative).unlink(missing_ok=True)
for chunk in (root / ".phase4").glob("chunk-*"):
    chunk.unlink()
(root / ".phase4").rmdir()

subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
subprocess.run(
    [
        "git",
        "config",
        "user.email",
        "41898282+github-actions[bot]@users.noreply.github.com",
    ],
    check=True,
)
subprocess.run(["git", "add", "-A"], check=True)
subprocess.run(
    [
        "git",
        "commit",
        "-m",
        "feat(services): introduce composable QA service lifecycle",
    ],
    check=True,
)
subprocess.run(
    ["git", "push", "origin", "HEAD:phase4/composable-services"],
    check=True,
)
