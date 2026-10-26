#!/usr/bin/env python3
"""Create a file URI for a Windows path rooted on its current drive."""

from __future__ import annotations

import ntpath
import subprocess
import sys
from urllib.parse import quote


def windows_file_uri(windows_path: str) -> str:
    """Return a local-host URI so Windows keeps the drive as an absolute root."""
    drive, tail = ntpath.splitdrive(windows_path)
    if not drive or not tail.startswith(("\\", "/")):
        raise ValueError(f"expected an absolute drive path, got: {windows_path!r}")
    path_from_drive_root = tail.lstrip("\\/").replace("\\", "/")
    if not path_from_drive_root:
        raise ValueError(f"expected a path below the drive root, got: {windows_path!r}")
    drive_letter = drive.replace("\\", "")
    return (
        "file://localhost/"
        + drive_letter
        + "/"
        + quote(path_from_drive_root, safe="/")
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: windows-file-uri.py <WSL path>")
    windows_path = subprocess.check_output(
        ["wslpath", "-w", sys.argv[1]], text=True
    ).strip()
    print(current_drive_rooted_file_uri(windows_path))


if __name__ == "__main__":
    main()
