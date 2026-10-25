#!/usr/bin/env python3
"""Skip only the failing BigQuery REST NULL-array statement in a test checkout."""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path("test/sql/functions/function_bigquery_query_rest.test")
EXPECTED_BLOCK = r"""# Type coverage: ARRAY with NULL elements
# BigQuery rejects query results that contain ARRAY values with NULL elements.
statement error
SELECT * FROM bigquery_query('${BQ_TEST_PROJECT}', '
    SELECT [1, NULL, 3] AS arr
', use_rest_api=true);
----
<REGEX>:Binder Error: Query execution failed: BigQuery does not allow query results with ARRAY values that contain NULL elements\. Original error: .+"""
SKIP_COMMENT = "# Disabled in Irion QA: BigQuery REST NULL-array error expectation.\n# Community extension currently returns an array instead of an error.\n"


def disable_case(upstream_root: Path) -> bool:
    path = upstream_root / TARGET
    original = path.read_text(encoding="utf-8")
    found = original.count(EXPECTED_BLOCK)
    if found == 1:
        path.write_text(original.replace(EXPECTED_BLOCK, SKIP_COMMENT, 1), encoding="utf-8")
        return True
    if found == 0 and original.count(SKIP_COMMENT) == 1:
        return False
    # BigQuery v0.13.0 fixes the earlier error expectation upstream.
    # Keep its valid ARRAY-of-STRUCTs assertions and error sentinel.
    if (
        found == 0
        and "# Wrap nullable values in non-NULL STRUCT elements" in original
        and "SELECT [STRUCT(1 AS id), STRUCT(CAST(NULL AS INT64) AS id), STRUCT(3 AS id)] AS arr" in original
        and "REST query failure sentinel" in original
        and "SELECT [1, NULL, 3] AS arr" not in original
    ):
        return False
    raise ValueError(
        f"BigQuery REST NULL-array expectation has changed: found {found} "
        f"matching cases in {path}; expected 1"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: skip-bigquery-rest-null-array-test.py UPSTREAM_ROOT")
    try:
        changed = disable_case(Path(sys.argv[1]))
        print(f"BigQuery REST NULL-array case skipped (changed={changed})", flush=True)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
