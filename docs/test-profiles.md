# Declarative test profiles

A test battery describes source ownership, the runner and shared extensions. Its
`profiles` collection describes the ordered SQLLogicTest executions performed by
that battery.

```yaml
profiles:
  - name: sql
    tests: test/sql/*
    testConfig:
      kind: generated
      excludedExtensions: []
      staticallyLoadedExtensions:
        - core_functions
        - parquet
```

## Global extensions

Entries in `defaultExtensions` are resolved into every enabled battery. BigQuery is
registered there with the community origin, so every generated or upstream profile
installs and loads it unless a future execution-scenario contract explicitly permits
an exclusion.

```yaml
defaultExtensions:
  - name: bigquery
    isUsed: true
    installFrom: community
```

The current maintained contract treats BigQuery as globally required. Configuration
tests verify that every matrix case contains `bigquery` with `installFrom: community`.

## Generated configurations

`kind: generated` creates a SQLLogicTest configuration from the resolved extension
set. `excludedExtensions` controls which extensions are intentionally not loaded
for that profile. This supports targeted lifecycle and autoloading tests without
adding battery-name conditions to the runner.

```yaml
- name: autoload
  tests: test/sql/autoloading/autoload_data_path.test
  testConfig:
    kind: generated
    excludedExtensions:
      - httpfs
      - postgres_scanner
      - sqlite_scanner
    staticallyLoadedExtensions:
      - core_functions
      - parquet
```

## HTTPFS scope

The HTTPFS compatibility battery intentionally contains only the `sql` profile:

```yaml
profiles:
  - name: sql
    tests: test/sql/*
```

The upstream `test/extension/*` suite is outside the maintained HTTPFS compatibility
scope and is not compiled into the execution plan. It is excluded by omitting that
profile rather than by moving or individually skipping the upstream files.

## BigQuery scope

The BigQuery battery is pinned to the source revision registered by DuckDB community
extensions and runs the upstream `test/sql/*` suite:

```yaml
bigquery:
  repository: hafenkran/duckdb-bigquery
  pin: 0c55a9b81646002edc0c73f36b703c8c39cea2ab
  setup: bigquery-gcp
  profiles:
    - name: all
      tests: test/sql/*
```

The `bigquery-gcp` setup requires these repository secrets:

- `GCS_SERVICE_ACCOUNT_KEY`: the service-account JSON used by the Google auth action;
- `BQ_TEST_PROJECT`: the Google Cloud project used by the upstream tests;
- `BQ_TEST_DATASET`: the disposable dataset used by the upstream tests.

The workflow selects authentication from `matrix.setup`, not from the battery name.
The standard runner also validates `GOOGLE_APPLICATION_CREDENTIALS`,
`BQ_TEST_PROJECT` and `BQ_TEST_DATASET`, so local executions fail clearly when the
GCP prerequisite is missing.

## Upstream configurations

`kind: upstream` starts from a configuration stored in the pinned upstream
checkout. The QA runtime adds the resolved extensions, generated connection SQL,
summary behavior and profile-scoped ignored tests.

```yaml
- name: sqlite
  tests: test/sql/*
  testConfig:
    kind: upstream
    path: test/configs/sqlite.json
```

## Runtime setup

A profile can currently request one maintained runtime setup:

```yaml
runtimeSetup: ducklake-postgres-15
```

Battery-level setup currently includes HTTPFS services, PostgreSQL, SQL Server and
BigQuery GCP credentials. These remain closed, non-composable contracts during phase
3. Service and prerequisite lifecycle will be extracted into composable contracts in
the next refactoring phase.

## Execution order

Profiles run in YAML order inside the battery job. The standard runner reads the
compiled profile list and performs the same sequence for every battery:

1. validate the battery-level prerequisite;
2. prepare the profile-specific SQLLogicTest configuration;
3. start the requested runtime setup;
4. execute the declared test filter;
5. validate that configured extension requirements were not silently skipped.

The runner never selects behavior from the battery name.
