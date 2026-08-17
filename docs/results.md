# Structured QA results

Every enabled execution-plan case writes a versioned `result.json` artifact. The
result is generated even when setup, authentication or test execution fails.

## Per-case result

A result records:

- battery, runner, duration and exit code;
- pinned upstream repository and observed commit;
- every profile with discovered, executed, passed, failed and skipped counts;
- expected extension installation and load state;
- declared battery and profile services;
- whether a failure is explicitly accepted by the compiled execution plan.

The result writer parses both successful DuckDB summaries and Catch-style failure
summaries. A test log containing failed test cases produces a failed result even when
the upstream executable returns exit code zero.

## Test counts are informational

There is no numeric coverage or skip baseline. In particular, the aggregate verdict
does not compare `discovered`, `executed` or `skipped` against hard-coded expected
counts.

This is intentional: upstream suites can add or reclassify tests without requiring a
manual update of the QA repository. Skipped/non-executed counts remain visible in the
structured result and in the human-readable summary so a reviewer can judge test
coverage and configuration quality.

A profile that reports only skipped tests is therefore not failed just because of the
number of skips. A real failed test, invalid test output, missing result or runner
failure still fails the battery.

## Aggregate verdict

The final aggregate jobs download every structured result artifact and check that:

1. every expected execution-plan case reported exactly once;
2. no unknown or duplicate case reported;
3. every result conforms to `test-result-v1.schema.json`;
4. accepted failures match the execution plan;
5. actual test/runner failures remain failures.

The Markdown report exposes the human quality metrics directly:

```text
Case | Profile | OK tests | KO tests | Skipped / not executed
```

Skipped/non-executed counts are informational and do not affect the verdict.

The aggregate jobs publish Linux and Windows summaries separately. Missing,
duplicate, invalid or failed results make the corresponding aggregate job fail.
