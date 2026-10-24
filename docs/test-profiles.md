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

BigQuery remains in the shared extension set even though its test battery is
temporarily disabled. Configuration tests verify that every selected matrix case
contains `bigquery` with `installFrom: community`.

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
extensions and runs the upstream `test/sql/*` suite against the configured GCP
project, dataset and service account. The source pin and binary lock are checked
alongside the enabled battery.

```yaml
bigquery:
  isEnabled: true
  repository: hafenkran/duckdb-bigquery
  pin: 5439a6a58439af4c05064f80a28b159c5a1424e7
  prerequisites:
    - type: google-bigquery
    - type: external-cloud-account
  profiles:
    - name: all
      tests: test/sql/*
```

These GitHub Actions secrets and values supply its external account:

- `GCS_SERVICE_ACCOUNT_KEY`: the service-account JSON used by the Google auth action;
- `BQ_TEST_PROJECT`: the Google Cloud project used by the upstream tests;
- `BQ_TEST_DATASET`: the disposable dataset used by the upstream tests.

The workflow needs `GCS_SERVICE_ACCOUNT_KEY`, `BQ_TEST_PROJECT` and
`BQ_TEST_DATASET`. The standard runner validates `GOOGLE_APPLICATION_CREDENTIALS`,
`BQ_TEST_PROJECT` and `BQ_TEST_DATASET`, so a run fails clearly when the GCP
prerequisite is missing.

## Azure cloud profile

The matrix resolver adds a `cloud` profile for `test/sql/cloud/*`. Linux and
Windows workflows initialize and bootstrap the configured Azure test account
before starting that profile. The workflows read `AZURE_TENANT_ID`,
`AZURE_CLIENT_ID` and `AZURE_CLIENT_SECRET` from Actions secrets, and the Azure
storage account and fixture roots from Actions variables. The bootstrap uploads
the pinned upstream fixtures and creates isolated write prefixes for each run.
Keep the credentials and account configuration in GitHub Actions settings; the
repository stores only the variable names and setup code.

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

## Services

A profile declares local dependencies using its `services` list. For example, the
DuckLake PostgreSQL profile starts a PostgreSQL service for that profile only:

```yaml
profiles:
  - name: postgres
    tests: test/sql/*
    services:
      - name: postgres-catalog
        type: postgres
        version: "15"
        database: ducklakedb
        username: postgres
        port: 5432
```

Battery-level services and prerequisites are declared in the configuration and
started by the shared service manager. Both platform matrices include Azure's local
Azurite and proxy profiles plus its cloud profile. The cloud profile uses the
configured account and the workflow bootstrap. BigQuery's external prerequisites
are declared separately from its local services.

## Execution order

Profiles run in YAML order inside the battery job. The standard runner reads the
compiled profile list and performs the same sequence for every battery:

1. validate the battery-level prerequisite;
2. prepare the profile-specific SQLLogicTest configuration;
3. start the requested profile services;
4. execute the declared test filter;
5. validate that configured extension requirements were not silently skipped.

The runner never selects behavior from the battery name.
