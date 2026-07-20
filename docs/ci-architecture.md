# CI Architecture

## Objective

Validate a selected DuckDB version against every extension used by Irion while executing the original upstream extension tests.

The CI has one strict compilation boundary:

```text
Compiled here:     DuckDB + unittest
Never compiled:    DuckDB extensions
```

Extension repositories are checked out only after the shared DuckDB build, and only by test jobs that need their tests or fixtures.

## Pipeline stages

### 1. Validate configuration

The first job reads `config/extensions.yml` and verifies:

- DuckDB and CI tooling are pinned;
- every enabled extension has a canonical name;
- every test source has an immutable commit SHA;
- install and load statements are present;
- every test group has a runner, test root, include filter, timeout, and adapter;
- every referenced adapter exists;
- no manifest entry requests extension compilation.

The validation job generates two machine-readable outputs:

1. the complete enabled extension set;
2. the parallel test-group matrix.

### 2. Build DuckDB once

One job checks out the selected DuckDB commit and `extension-ci-tools`, creates the standard DuckDB build environment, and builds only:

```bash
cmake --build build/release \
  --target duckdb unittest
```

The job must reject configurations containing extension CMake files or extension build targets.

It publishes one immutable artifact containing:

```text
build/release/duckdb
build/release/test/unittest
DuckDB commit metadata
compiler and platform metadata
```

### 3. Fan out parallel test groups

After the DuckDB artifact is available, GitHub Actions creates one job per configured test group.

Example matrix:

```json
[
  {"extension":"fts","group":"fts-sqllogic","adapter":"none"},
  {"extension":"spatial","group":"spatial-sqllogic","adapter":"none"},
  {"extension":"postgres","group":"postgres-sqllogic","adapter":"postgres"}
]
```

These jobs run in parallel and all download the same DuckDB artifact.

A test-group job must never invoke CMake or rebuild DuckDB.

### 4. Create an isolated runtime

Every test-group job creates independent paths for:

- HOME;
- DuckDB extension installation;
- temporary files;
- database files;
- service containers and networks;
- test output and logs.

This prevents globally installed extensions or another parallel group from influencing the result.

### 5. Prepare the group adapter

The selected adapter prepares the environment required by the upstream group.

The `none` adapter performs no external setup.

A future `postgres` adapter will:

1. start a PostgreSQL container pinned by version or digest;
2. wait for `pg_isready` or an equivalent health check;
3. initialize databases, users, schemas, and fixtures;
4. produce a connection string;
5. expose the connection string under the environment variable expected by the upstream tests;
6. capture PostgreSQL logs;
7. tear down the service after the group completes.

Adapters prepare infrastructure only. They do not compile DuckDB or extensions.

### 6. Install and load every enabled extension

The test job generates a DuckDB test configuration containing the install and load statements of the complete enabled extension set.

For example:

```sql
INSTALL fts;
INSTALL spatial;
INSTALL postgres;

LOAD fts;
LOAD spatial;
LOAD postgres;
```

This configuration is used for every group, including the FTS, Spatial, and PostgreSQL groups.

Before upstream tests run, a pre-flight query verifies:

- every enabled extension is installed;
- every enabled extension is loaded;
- each extension came from its declared binary source;
- no unexpected extension was substituted;
- the effective extension versions are recorded.

Any missing install or load is a hard failure.

## 7. Check out and discover upstream tests

The job checks out the owner extension repository at the configured immutable commit.

For an FTS group:

```text
repository: https://github.com/duckdb/duckdb-fts.git
commit:    6814ec9a7d5fd63500176507262b0dbf7cea0095
```

The job inventories matching files before execution. Zero discovered tests is a hard failure unless the manifest explicitly defines a no-tests contract.

Tests remain in the upstream checkout and are not copied into this repository.

## 8. Execute the group

A SQLLogicTest group is run through the shared DuckDB runner:

```bash
unittest \
  --test-config generated/all-extensions-loaded.json \
  --test-dir upstream/fts \
  "test/sql/fts/*"
```

The working directory and environment must preserve upstream fixtures and relative paths.

If an extension repository uses a different test system, its adapter or runner implementation invokes that upstream system using the shared DuckDB binary where applicable. Unsupported test categories must be reported explicitly.

## 9. Publish evidence

Each group publishes an artifact containing:

- resolved manifest entry;
- DuckDB and test-source commits;
- generated all-extensions-loaded configuration;
- extension inventory before and after loading;
- discovered test list;
- executed test list;
- passed, failed, skipped, crashed, and timed-out counts;
- adapter setup and service logs;
- stdout, stderr, and exit code;
- redacted environment metadata.

A final aggregation job combines the group results into one compatibility report.

## Adding a new extension

Adding an extension should not require editing the central workflow.

The expected flow is:

1. add the extension and its test groups to `config/extensions.yml`;
2. add an adapter directory only if special infrastructure is required;
3. validate the manifest;
4. let the generated matrix create the new parallel job;
5. verify that all existing groups now load the newly enabled extension as well.

The new extension therefore creates two forms of coverage:

- its own upstream test group;
- renewed coexistence coverage across every previously configured group.

## Example: PostgreSQL-backed group

```text
Shared DuckDB artifact
        │
        ▼
PostgreSQL test job
        │
        ├── start PostgreSQL container
        ├── wait for health check
        ├── create fixtures
        ├── generate connection string
        ├── INSTALL and LOAD all Irion extensions
        ├── checkout postgres_scanner tests at pinned commit
        └── run PostgreSQL upstream tests with --test-dir
```

The PostgreSQL container belongs only to that test group. FTS or Spatial groups do not start it, but they still load the PostgreSQL DuckDB extension because all enabled extensions are present in every group.
