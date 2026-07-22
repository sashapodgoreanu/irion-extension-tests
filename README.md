# Irion DuckDB Extension Compatibility QA

This repository verifies that the DuckDB extensions used together by Irion remain compatible with a selected DuckDB release.

A single DuckDB CLI and `unittest` runtime is built once and shared by several upstream test batteries running in parallel. Each battery checks out an immutable upstream pin, prepares its required services and fixtures, resolves its extension set from configuration, and executes the upstream SQLLogicTests without copying them into this repository.

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
          ┌───────────────────┼───────────────────┬───────────────────┐
          ▼                   ▼                   ▼                   ▼
     HTTPFS tests        DuckLake tests    postgres_scanner      MSSQL tests
       upstream             upstream           upstream             upstream
       pinned               pinned             pinned               release tag
```

The build happens once. Every enabled battery runs as an independent matrix job and downloads the same runtime artifact.

## Configuration model

### DuckDB runtime

```yaml
duckdb:
  version: v1.5.4
  ciToolsVersion: v1.5.4
```

These values drive the build, cache key, artifact name, extension directory, and every battery runtime. They must not be duplicated in the workflow.

### Default extensions

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
```

The current baseline is:

- `httpfs`;
- `mssql` from the DuckDB Community repository;
- `ducklake`;
- `postgres_scanner`.

Set `isUsed: false` to remove an extension only from the shared baseline:

```yaml
- name: ducklake
  isUsed: false
```

This does not disable the DuckLake battery or any other battery.

### Test batteries

Each entry under `testBatteries` defines one possible parallel job:

```yaml
testBatteries:
  postgres_scanner:
    isEnabled: true
    runner: postgres-scanner
    repository: duckdb/duckdb-postgres
    pin: 8f813f9b9c9e52a9074a050a0be60f49160a6baa
    tests: test/sql/*
    submodules: recursive
    setup: postgres-17
    extensions:
      - name: postgres_scanner
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

### Independent switches: `isEnabled` and `isUsed`

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
  - name: httpfs
    isUsed: false

testBatteries:
  httpfs:
    isEnabled: true
    extensions:
      - name: httpfs
        isUsed: true
```

The HTTPFS battery still runs and still receives `httpfs`; other batteries no longer receive `httpfs` through the shared baseline.

The inverse is also valid:

```yaml
defaultExtensions:
  - name: httpfs
    isUsed: true

testBatteries:
  httpfs:
    isEnabled: false
```

The HTTPFS battery is not scheduled, but `httpfs` remains loaded by default in every other enabled battery.

When the same active extension appears in both lists, it is present once in the resolved runtime. Conflicting `installFrom` values are rejected.

A deliberate test profile may temporarily start an installed extension unloaded when that behavior is under test. HTTPFS autoloading and MSSQL dynamic loading use this mechanism; it does not change the YAML-level independence described above.

### Battery-specific extensions

A battery declares its target extension and any additional dependencies:

```yaml
extensions:
  - name: ducklake
    isUsed: true
  - name: tpch
    isUsed: true
  - name: tpcds
    isUsed: true
  - name: azure
    isUsed: false
```

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

### Ignored tests

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

## Current batteries

| Battery | Upstream pin | Main tests | Setup |
|---|---|---|---|
| HTTPFS | `c3f215ab360f04dc3d3d5305fa81849c0121f111` | `test/sql/*` plus upstream autoload tests | HTTP server, Squid, MinIO/S3 fixtures |
| DuckLake | `d318a545571d7d46eb751fa2aa5f6f4389285d3c` | `test/sql/*` | SQLite and PostgreSQL catalog profiles |
| postgres_scanner | `8f813f9b9c9e52a9074a050a0be60f49160a6baa` | `test/sql/*` | PostgreSQL 17 and upstream fixtures |
| MSSQL | release `v0.2.1` | `test/sql/*` | SQL Server 2022 and upstream release fixtures |

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

The upstream `test/configs/sqlite.json` and `test/configs/postgres.json` files remain authoritative. The adapter merges the resolved extension initialization and profile-specific ignored tests while preserving upstream fields.

### postgres_scanner

The postgres scanner battery follows the commit declared by DuckDB `v1.5.4`, starts PostgreSQL 17, and runs the pinned repository’s `create-postgres-tables.sh` fixture script.

It verifies that the installed `postgres_scanner` binary reports the same source commit as the checked-out tests before executing `test/sql/*`.

### MSSQL

MSSQL follows a published release tag, never `main`. The configured tag is checked against the exact checkout and against the source commit reported by the Community extension binary.

The runner reuses the pinned release’s SQL Server Compose definition, seed SQL, integration smoke test, and complete SQLLogicTest folder.

A runtime copy of the legacy base runner removes its old hardcoded skip list. All ignored MSSQL tests are controlled by `config/extensions.yml`.

To update MSSQL:

1. select a newer published release tag;
2. verify that `duckdb/community-extensions` publishes the binary from the same tag;
3. change the YAML pin and review changed upstream service or fixture contracts;
4. remove or update stale ignored tests when validation reports them.

## Files

```text
config/extensions.yml                         single source of QA configuration
.github/workflows/extension-qa.yml            generic configure/build/matrix pipeline
scripts/resolve-extension-config.py           validates YAML and emits the matrix
scripts/prepare-test-battery.py               generates per-job SQL and metadata
scripts/run-test-battery.sh                   generic runtime dispatcher
scripts/run-standard-tests.sh                 HTTPFS, DuckLake, and generic batteries
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
