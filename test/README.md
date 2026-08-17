# Irion compatibility tests

The `irion` battery runs repository-owned SQLLogicTests through the same GitHub Actions matrix and shared DuckDB runtime model used by the upstream extension batteries.

The battery uses `source: self`. Its tests are executed directly from the QA repository workspace, so it does not check out this repository a second time and does not depend on a feature branch or another permanent branch reference.

The current validation targets are Linux/x86_64 and Windows/x86_64. Runtime values are compiled into the execution plan and recorded in every structured result and aggregate summary.

## Layout

```text
test/
├── configs/
│   └── irion.json
├── scripts/
│   └── irion/
│       └── initialize.sql
└── sql/
    └── irion/
        ├── initialization.test
        ├── extension_baseline.test
        ├── transaction_flow.test
        └── json_interaction.test
```

## Configuration

`test/configs/irion.json` is a normal DuckDB SQLLogicTest configuration. It may define the same settings used by upstream repositories, including:

- `init_script` for repository-owned initialization SQL;
- `on_init` for SQL executed when the test runner starts;
- `on_new_connection` for SQL executed for every test connection;
- `test_env` for test-specific environment variables;
- `skip_tests` and `skip_error_messages` when explicitly justified.

The QA runner combines the repository `init_script` and `on_init` with the extension installation and loading script resolved from `config/extensions.yml`.

## Adding a scenario

1. Add one or more `.test` files below `test/sql/irion/`.
2. Put reusable setup SQL below `test/scripts/irion/`.
3. Reference the setup file from `test/configs/irion.json`, or add another Irion profile in `config/extensions.yml` with a separate test config.
4. Declare temporary services on the battery or profile when the scenario needs PostgreSQL, SQL Server, MinIO, Azurite, Squid, or another supported service.

No numeric baseline needs to be updated when tests are added. The configured paths/globs discover the suite dynamically.

## Skipped and non-executed tests

Skipped/non-executed tests are reported as quality information, not used as a numeric pass/fail gate. The aggregate summary exposes per-profile counts for:

- OK tests;
- KO tests;
- skipped/non-executed tests.

There is deliberately no expected skip count, maximum skip count, minimum executed count, or other hand-maintained numeric baseline. If an upstream or Irion suite grows, the QA repository does not require a count update.

Actual failed tests, invalid test output, runner failures, missing results, duplicate results and unexpected result cases still fail the aggregate verdict. Explicit `ignoredTests` remain documented exclusions with a mandatory reason, and unavailable approved external prerequisites remain visible in the structured result.
