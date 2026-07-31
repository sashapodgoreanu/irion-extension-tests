# Irion compatibility tests

The `irion` battery runs repository-owned SQLLogicTests through the same GitHub Actions matrix and the same shared DuckDB runtime used by the upstream extension batteries.

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
        └── extension_baseline.test
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

The battery must remain free of undeclared skips. A missing initialization script, missing test profile, failed assertion, or unexpected skipped test makes the matrix result fail.
