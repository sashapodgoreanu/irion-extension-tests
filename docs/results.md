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

## Coverage policy

Coverage thresholds are maintained independently in `config/result-policy.yml`:

```yaml
schemaVersion: 1

defaults:
  minimumDiscovered: 1
  minimumExecuted: 1

overrides: []
```

The default policy prevents a battery from appearing healthy when every discovered
test was skipped. Optional exact case/profile overrides can set:

- `minimumDiscovered`;
- `minimumExecuted`;
- `maximumSkipped`.

Accepted external-account failures are not evaluated against coverage thresholds,
because their profiles may not start. Only cases carrying the compiled
`accepted-failure` capability can use that status.

## Aggregate verdict

The final `Aggregate structured results` job downloads every `result-*` artifact and
checks that:

1. every expected execution-plan case reported exactly once;
2. no unknown or duplicate case reported;
3. every result conforms to `test-result-v1.schema.json`;
4. accepted failures match the execution plan;
5. coverage thresholds are satisfied.

It publishes:

```text
qa-result-summary/summary.json
qa-result-summary/summary.md
```

Missing, duplicate, invalid, failed or under-covered results make the aggregate job
fail.
