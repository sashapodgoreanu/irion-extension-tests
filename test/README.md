# Irion compatibility tests

The `irion` battery runs repository-owned SQLLogicTests through the same GitHub Actions matrix and the same shared DuckDB runtime used by the upstream extension batteries.

The battery uses `source: self`. Its tests are executed directly from the QA repository workspace, so it does not check out this repository a second time and does not depend on a feature branch or another permanent branch reference.

The current validation contract is explicit:

- operating system: `linux`;
- architecture: `x86_64`;
- GitHub Actions runner: `ubuntu-24.04`.

These runtime values are compiled into the execution plan, included in cache and artifact identities, and recorded in every structured result and aggregate summary.

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
5. Update `config/result-policy.yml` so the expected number of discovered and executed tests cannot silently decrease.

## Non-execution policy

The final summary distinguishes four categories:

- **upstream declared**: a known number of tests that the pinned upstream suite does not execute for a profile; these counts are authorized in `config/result-policy.yml` with a mandatory reason;
- **Irion exclusions**: files explicitly removed through `ignoredTests`, each with a mandatory reason and optional profile scope;
- **external prerequisite**: a battery that cannot run because an approved external account or credential is unavailable;
- **unexpected**: any observed non-execution that is not covered by an exact upstream authorization.

The aggregator compares `discovered - executed` with the authorized upstream count for every profile. A new skip, a removed skip authorization that has not been cleaned up, duplicate authorizations, missing metrics, or a drop below the configured discovery/execution baseline fails the aggregate verdict.

The Irion battery must remain free of undeclared skips. A missing initialization script, missing test profile, failed assertion, or unexpected skipped test makes the matrix result fail.
