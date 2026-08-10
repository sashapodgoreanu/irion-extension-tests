#!/usr/bin/env python3
"""Translate mounted WSL paths before invoking native Windows DuckDB binaries."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

WSL_PATH = re.compile(r"/mnt/([A-Za-z])((?:/[^\s'\";,)]*)?)")


def translate_text(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        drive = match.group(1).upper()
        tail = match.group(2) or ""
        return f"{drive}:{tail}"

    return WSL_PATH.sub(replace, value)


def translate_value(value: Any) -> Any:
    if isinstance(value, str):
        return translate_text(value)
    if isinstance(value, list):
        return [translate_value(item) for item in value]
    if isinstance(value, dict):
        return {key: translate_value(item) for key, item in value.items()}
    return value


def translate_config(source: Path, destination: Path) -> None:
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(translate_value(payload), indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    text_parser = subparsers.add_parser("translate-text")
    text_parser.add_argument("value")

    config_parser = subparsers.add_parser("translate-config")
    config_parser.add_argument("source", type=Path)
    config_parser.add_argument("destination", type=Path)

    args = parser.parse_args()
    if args.command == "translate-text":
        print(translate_text(args.value), end="")
        return 0
    if args.command == "translate-config":
        translate_config(args.source, args.destination)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
