"""Include REST error bodies in failures from the Unity Catalog pytest suite."""

from __future__ import annotations

import json
import sys
from urllib.error import HTTPError


def pytest_runtest_makereport(item, call):
    """Report the server response when a test leaves an HTTPError uncaught."""
    if call.excinfo is None:
        return

    error = call.excinfo.value
    if not isinstance(error, HTTPError):
        return

    try:
        body = error.read(8192).decode("utf-8", errors="replace")
    except Exception as read_error:  # pragma: no cover - diagnostic fallback only
        body = f"<could not read error body: {read_error}>"

    print(
        "Unity Catalog REST failure "
        + json.dumps(
            {
                "test": item.nodeid,
                "status": error.code,
                "reason": error.reason,
                "body": body,
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
