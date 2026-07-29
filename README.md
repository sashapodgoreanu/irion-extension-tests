# Irion DuckDB Extension Compatibility QA

This repository verifies that the DuckDB extensions used together by Irion remain compatible with a selected DuckDB release.

A single DuckDB CLI and `unittest` runtime is built once and shared by several upstream test batteries running in parallel. Each battery checks out an immutable upstream pin, resolves its extension set from configuration, prepares any required services or fixtures, and executes the original upstream SQLLogicTests without copying them into this repository.

## Single source of configuration

All selectable QA configuration lives in:

```text
config/extensions.yml
```

The GitHub Actions workflow does not contain a hardcoded matrix of repositories, pins, test filters, enabled batteries, ignored tests, or extension lists. The initial `configure` job validates the YAML and generates the matrix dynamically.

The YAML controls:

- DuckDB and `extension-ci-tools` versions;
- the extensions loaded by default in every enabled battery;
- `isUsed: true|false` for default and battery-specific extensions;
- `isEnabled: true|false` for each test battery;
- repository, immutable pin, test filter, submodules, runner, and setup;
- ignored tests, globally or for a supported profile.

Invalid configuration fails before the DuckDB build starts.

## Workflow architecture

```text
                    config/extensions.yml
                              │
                              ▼
                   Resolve configuration
             validate YAML + generate JSON matrix
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
       Prepare DuckDB runtime        enabled batteries
       DuckDB CLI + unittest          from YAML only
                 │                         │
                 └──────── shared artifact┘
                              │
      ┌───────────┬───────────┬───────────┬───────────┐
      ▼           ▼           ▼           ▼           │
   HTTPFS      DuckLake    PostgreSQL    MSSQL         │
      │           │           │           │           │
      ├───────────┼───────────┼───────────┼───────────┤
      ▼           ▼           ▼           ▼
    Delta       Iceberg      Azure     Unity Catalog
```

The build happens once. Every enabled battery runs as an independent matrix job and downloads the same runtime artifact.

## DuckDB runtime

```yaml
duckdb:
  version: v1.5.5
  ciToolsVersion: v1.5.5
```

These values drive the build, cache key, artifact name, extension directory, and every battery runtime. They must not be duplicated in the workflow.

## Default extensions

`defaultExtensions` is the shared compatibility baseline installed and loaded in every enabled battery:

```yaml
defaultExtensions:
  - name: httpfs
    isUsed: true

  - name: mssql
    isUsed: true
    installFrom: community

  - name: ducklake
    isUsed: true

  - name: postgres_scanner
    isUsed: true

  - name: icu
    isUsed: true

  - name: azure
    isUsed: true

  - name: delta
    isUsed: true

  - name: iceberg
    isUsed: true

  - name: unity_catalog
    isUsed: true

  - name: bigquery
    isUsed: true
    installFrom: community
```

The ordering is intentional:

- filesystem providers are loaded before extensions that consume remote storage;
- `delta` is loaded before `unity_catalog`;
- `unity_catalog` can therefore use the Delta implementation from the same DuckDB runtime.

The current baseline is:

- `httpfs`;
- `mssql` from the DuckDB Community repository;
- `ducklake`;
- `postgres_scanner`;
- `icu`;
- `azure`;
- `delta`;
- `iceberg`;
- `unity_catalog`;
- `bigquery` from the DuckDB Community repository.

Set `isUsed: false` to remove an extension only from the shared baseline:

```yaml
- name: iceberg
  isUsed: false
```

This does not disable the Iceberg battery or any other battery.

## Test batteries

Each entry under `testBatteries` defines one possible parallel job:

```yaml
testBatteries:
  delta:
    isEnabled: true
    runner: standard
    repository: duckdb/duckdb-delta
    pin: 45c40878601b54b4188b09e08732fe0d576ad222
    tests: test/sql/*
    submodules: recursive
    setup: none
    extensions:
      - name: httpfs
        isUsed: true
      - name: azure
        isUsed: true
      - name: aws
        isUsed: true
      - name: delta
        isUsed: true
```

Supported fields:

| Field | Meaning |
|---|---|
| `isEnabled` | Schedules or suppresses only this battery job. |
| `runner` | Selects the maintained runner contract. |
| `repository` | Upstream repository in `owner/name` form. |
| `pin` | Exact commit or published release tag checked out by Actions. |
| `tests` | Main SQLLogicTest filter for the battery. |
| `submodules` | `true`, `false`, or `recursive`. |
| `setup` | Named service/setup contract used by the generic workflow. |
| `extensions` | Target extension and other requirements specific to this battery. |
| `ignoredTests` | Explicit upstream tests excluded by configuration. |

Supported setup contracts are `none`, `httpfs-services`, `ducklake-catalogs`, `postgres-17`, and `sqlserver-2022`.

To keep a battery configured but stop scheduling it:

```yaml
isEnabled: false
```

## Independent switches: `isEnabled` and `isUsed`

Battery scheduling and extension selection are intentionally independent.

| Configuration change | Effect on battery jobs | Effect on default extensions |
|---|---|---|
| `testBatteries.<name>.isEnabled: false` | Only that battery is not scheduled. | No default extension is removed or changed. |
| `defaultExtensions.<extension>.isUsed: false` | No battery is disabled. | The extension is removed only from the shared baseline. |
| `testBatteries.<name>.extensions[].isUsed: true` | The extension is required by that battery when it runs. | It does not become a default for other batteries. |
| `testBatteries.<name>.extensions[].isUsed: false` | The battery remains enabled. That entry adds nothing. | An active default with the same name still remains available. |

Two invariants therefore hold:

1. **Disabling a test battery never removes its extension from `defaultExtensions`.**
2. **Removing an extension from `defaultExtensions` never disables its test battery.**

Each battery explicitly declares its own target extension in its `extensions` list, even when that extension is also active in `defaultExtensions`. The resolver merges and de-duplicates the two sources.

Example:

```yaml
defaultExtensions:
  - name: delta
    isUsed: false

testBatteries:
  delta:
    isEnabled: true
    extensions:
      - name: delta
        isUsed: true
```

The Delta battery still runs and receives `delta`; other batteries no longer receive Delta through the shared baseline.

The inverse is also valid:

```yaml
defaultExtensions:
  - name: delta
    isUsed: true

testBatteries:
  delta:
    isEnabled: false
```

The Delta battery is not scheduled, but `delta` remains loaded by default in every other enabled battery.

When the same active extension appears in both lists, it is present once in the resolved runtime. Conflicting `installFrom` values are rejected.

## Battery-specific extensions

A battery declares its target extension and any additional dependencies required by its upstream tests.

The final runtime extension set is:

```text
active defaultExtensions
+
active battery.extensions
-
duplicates
```

The runtime generator creates the `INSTALL` and `LOAD` SQL for each job. No checked-in SQL file contains a static compatibility list.

`installFrom` selects a named DuckDB extension repository:

```yaml
- name: mssql
  isUsed: true
  installFrom: community
```

### Dependency examples

Delta follows its upstream test dependencies:

```yaml
extensions:
  - name: httpfs
    isUsed: true
  - name: azure
    isUsed: true
  - name: aws
    isUsed: true
  - name: delta
    isUsed: true
  - name: json
    isUsed: true
  - name: tpch
    isUsed: true
  - name: tpcds
    isUsed: true
```

Unity Catalog keeps its functional dependency explicit and ordered:

```yaml
extensions:
  - name: httpfs
    isUsed: true
  - name: delta
    isUsed: true
  - name: unity_catalog
    isUsed: true
  - name: tpch
    isUsed: true
  - name: tpcds
    isUsed: true
```

This means removing `delta` from the shared defaults does not make the Unity Catalog battery invalid: that battery still declares and loads Delta itself.

## DuckDB v1.5.5 pins

The core batteries use the exact extension commits declared by DuckDB tag `v1.5.5`.

| Extension | Upstream repository | DuckDB v1.5.5 pin |
|---|---|---|
| HTTPFS | `duckdb/duckdb-httpfs` | `827222fb45a043a7a852d1f7aae46901492a3cda` |
| DuckLake | `duckdb/ducklake` | `d8a1881e22516ea3d186d73e83c65fe5bd1a1dc4` |
| PostgreSQL Scanner | `duckdb/duckdb-postgres` | `41223e51559cd581f1c06e170b71c71df25bbaac` |
| Delta | `duckdb/duckdb-delta` | `45c40878601b54b4188b09e08732fe0d576ad222` |
| Iceberg | `duckdb/duckdb-iceberg` | `45163a28e0ed6a2071a82a1bf1dd432d0216cf9c` |
| Azure | `duckdb/duckdb-azure` | `003214c96d0caa39d5c3e27a9e1976a0692c7d37` |
| Unity Catalog | `duckdb/unity_catalog` | `fd851475780ca064d9706a5025ea6e5d1d9d7e23` |

Community extensions are resolved from the DuckDB Community Extensions catalog. BigQuery remains pinned to `0c55a9b81646002edc0c73f36b703c8c39cea2ab`; MSSQL advances to release `v0.2.2`, built for DuckDB `v1.5.5`.

These values are immutable test-source pins. Updating DuckDB requires reviewing the corresponding extension configuration files from the new DuckDB tag and changing the YAML intentionally.

## Current batteries

| Battery | Upstream pin | Main tests | Setup |
|---|---|---|---|
| HTTPFS | `827222fb45a043a7a852d1f7aae46901492a3cda` | `test/sql/*` plus upstream autoload tests | HTTP server, Squid, MinIO/S3 fixtures |
| DuckLake | `d8a1881e22516ea3d186d73e83c65fe5bd1a1dc4` | `test/sql/*` | SQLite and PostgreSQL catalog profiles |
| postgres_scanner | `41223e51559cd581f1c06e170b71c71df25bbaac` | `test/sql/*` | PostgreSQL 17 and upstream fixtures |
| Delta | `45c40878601b54b4188b09e08732fe0d576ad222` | `test/sql/*` | Standard runner; upstream environment-gated cloud/generated-data tests remain conditional |
| Iceberg | `45163a28e0ed6a2071a82a1bf1dd432d0216cf9c` | `test/sql/local/*` | Standard runner; external catalog and S3 profiles are not enabled yet |
| Azure | `003214c96d0caa39d5c3e27a9e1976a0692c7d37` | local Azurite and proxy suites | Azurite and Squid profiles |
| Unity Catalog | `fd851475780ca064d9706a5025ea6e5d1d9d7e23` | local OSS catalog suite | Local Unity Catalog OSS service |
| BigQuery | `0c55a9b81646002edc0c73f36b703c8c39cea2ab` | `test/sql/*` | External Google Cloud credentials; accepted failure when unavailable |
| MSSQL | release `v0.2.2` | `test/sql/*` | SQL Server 2022 and upstream release fixtures |

The table documents the current YAML values; `config/extensions.yml` remains authoritative.

### HTTPFS

The HTTPFS runner reuses service scripts from its pinned checkout, including the upstream HTTP server, Squid, presigned URL, and MinIO/S3 setup. The main SQL suite and the HTTPFS autoload suite run in the same job.

The autoload profile keeps HTTPFS installed but initially unloaded.

### DuckLake

DuckLake keeps three intentional profiles:

1. the dedicated filesystem-autoloading test with HTTPFS initially unloaded;
2. the upstream SQLite catalog configuration;
3. the upstream PostgreSQL catalog configuration with a temporary PostgreSQL 15 service.

The former generic `test/*` pass was removed because it repeated the same `test/sql/*` content already exercised by the SQLite and PostgreSQL profiles.

### postgres_scanner

The postgres scanner battery follows the commit declared by DuckDB `v1.5.5`, starts PostgreSQL 17, and runs the pinned repository’s `create-postgres-tables.sh` fixture script.

It verifies that the installed `postgres_scanner` binary reports the same source commit as the checked-out tests before executing `test/sql/*`.

### Delta

The Delta battery follows the commit declared by DuckDB `v1.5.5` and executes `test/sql/*`.

The upstream repository distinguishes:

- core dependencies: `json`, `tpch`, and `tpcds`;
- cloud dependencies: `httpfs`, `azure`, and `aws`;
- generated-data tests controlled by upstream environment and data availability.

All extension dependencies are declared in the battery. Tests that require external credentials or generated datasets remain governed by the upstream SQLLogicTest conditions.

### Iceberg

The Iceberg battery follows the DuckDB `v1.5.5` commit and initially executes `test/sql/local/*`.

The battery loads `httpfs`, `avro`, `tpch`, and `iceberg`. The external Fixture, Nessie, Lakekeeper, Polaris, MinIO/S3, Spark-data-generation, and cloud profiles are intentionally not started by the generic runner. They can be added later as named setup contracts without changing the workflow matrix.

### Azure

The Azure battery follows the DuckDB `v1.5.5` commit and executes its local Azurite and proxy profiles.

Tests requiring Azure storage accounts, connection strings, CLI authentication, service principals, access tokens, or managed identity remain controlled by their upstream `require-env` directives. The same job still verifies that Azure installs and loads together with every active default extension.

### Unity Catalog

The Unity Catalog battery follows the DuckDB `v1.5.5` commit and executes the local OSS catalog profile.

`delta` is declared explicitly and loaded before `unity_catalog`. Databricks-dependent tests remain controlled by their upstream environment checks.

### BigQuery

BigQuery follows the immutable commit currently published by the DuckDB Community Extensions catalog. The battery requires Google Cloud credentials and remains an accepted failure when the external account is unavailable.

### MSSQL

MSSQL follows a published release tag, never `main`. The configured tag is checked against the exact checkout and against the source commit reported by the Community extension binary.

The runner reuses the pinned release’s SQL Server Compose definition, seed SQL, integration smoke test, and complete SQLLogicTest folder.

A runtime copy of the legacy base runner removes its old hardcoded skip list. All ignored MSSQL tests are controlled by `config/extensions.yml`.

## Ignored tests

A global ignored test is removed from upstream discovery for the entire battery and recorded in `ignored-tests.tsv`:

```yaml
ignoredTests:
  - path: test/extension/autoloading_base.test
    reason: Assumes an empty extension installation
```

A profile-specific ignored test remains available to the other supported profile:

```yaml
ignoredTests:
  - path: test/sql/data_inlining/postgres_identifier_limit.test
    reason: Test is specific to the PostgreSQL catalog profile
    profiles:
      - sqlite
```

Profile-specific ignored tests are currently supported for the DuckLake `sqlite` and `postgres` catalog profiles. Other exclusions must be global to the battery.

Every ignored entry must contain both `path` and `reason`. If an ignored path no longer exists at the selected pin, the job fails so the exclusion must be reviewed.

## Runtime generation

For every matrix entry, `scripts/prepare-test-battery.py` creates an isolated runtime containing:

- the resolved battery JSON;
- resolved extension metadata;
- generated installation SQL;
- generated full initialization SQL;
- special profiles such as “without HTTPFS” and “without MSSQL”;
- global ignored-test metadata;
- profile-specific skip metadata.

The generated files are copied into the battery log artifact and are not source-controlled configuration.

Before executing tests, the runner queries `duckdb_extensions()` and verifies that every resolved extension is installed and loaded from the expected repository. SQLLogicTest summaries are checked so a selected extension cannot be silently skipped by `require`.

## Files

```text
config/extensions.yml                         single source of QA configuration
.github/workflows/extension-qa.yml            generic configure/build/matrix pipeline
scripts/resolve-extension-config.py           validates YAML and emits the matrix
scripts/prepare-test-battery.py               generates per-job SQL and metadata
scripts/run-test-battery.sh                   generic runtime dispatcher
scripts/run-standard-tests.sh                 standard and lakehouse batteries
scripts/run-postgres-scanner-tests.sh         PostgreSQL fixture and pin contract
scripts/run-mssql-configured-tests.sh         configured MSSQL compatibility wrapper
scripts/run-mssql-tests-base.sh               preserved MSSQL execution engine
scripts/prepare-mssql-configured-runner.py    removes legacy hardcoded MSSQL skips
scripts/prepare-ducklake-config.py            adapts upstream catalog profiles
scripts/validate-extension-probe.py           validates installed and loaded extensions
scripts/check-test-requirements.py            rejects silent SQLLogicTest require skips
scripts/setup-httpfs.sh                       coordinates pinned HTTPFS services
scripts/build.sh                              builds the shared DuckDB runtime
```

## Configuration validation

Run the same resolver used by GitHub Actions in an isolated virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install PyYAML==6.0.2
.venv/bin/python scripts/resolve-extension-config.py config/extensions.yml
```

The resolver validates the complete file, including disabled batteries, and emits the resolved matrix plus DuckDB version outputs.

## Adding another battery

1. Add a complete entry under `testBatteries`.
2. Choose an existing `runner` and `setup` contract, or implement a new named contract.
3. Pin an immutable upstream commit or published release tag.
4. Explicitly declare the target extension in the battery `extensions` list.
5. Declare additional dependencies required only by that battery.
6. Add ignored tests with explicit reasons only after observing reproducible incompatibilities.
7. Run the resolver and GitHub Actions.

No workflow matrix edit is required.

## CI triggers

The workflow runs on:

- `push`;
- `pull_request`;
- `workflow_dispatch`.

It can therefore be tested from any branch.
