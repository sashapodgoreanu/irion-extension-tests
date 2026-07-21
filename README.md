# Irion DuckDB Extension Compatibility POC

This repository checks whether the DuckDB extensions used together by Irion remain compatible with a selected DuckDB release.

The first version intentionally follows a small, explicit POC design.

## What is built

GitHub Actions uses the normal DuckDB extension-template build to compile:

- DuckDB `v1.5.4`;
- DuckDB `unittest`;
- one trivial local extension named `qa_test`.

`qa_test` exists only to drive the standard build. HTTPFS, DuckLake, MSSQL, and the other dependencies are downloaded rather than compiled here.

## Workflow

```text
                         build
               DuckDB + unittest + qa_test
                           │
                    shared artifact
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         HTTPFS tests  DuckLake tests  MSSQL tests
            test/*        test/*       test/sql/*
                                         │
                                  SQL Server 2022
```

The three test jobs run in parallel and download the same DuckDB build artifact.

## Extension bootstrap

Every job uses a clean `HOME` and installs the compatibility set once through `scripts/install-extensions.sql`:

```sql
INSTALL json;
INSTALL tpch;
INSTALL tpcds;
INSTALL icu;
INSTALL httpfs;
INSTALL ducklake;
INSTALL postgres_scanner;
INSTALL sqlite_scanner;
INSTALL mssql FROM community;
```

Normal test databases load the required extensions through init scripts. Additional connections reload the same profile through `on_new_connection`.

The runner prints `duckdb_extensions()` before the tests and fails when a required extension is missing, not loaded, or still appears in the skipped-test summary.

## Upstream test batteries

### HTTPFS

- Repository: `duckdb/duckdb-httpfs`
- Commit: `c3f215ab360f04dc3d3d5305fa81849c0121f111`
- Selection: `test/*`

The job reuses the infrastructure scripts from that exact HTTPFS checkout:

- `scripts/run_squid.sh`;
- `scripts/generate_presigned_url.sh`;
- `scripts/run_s3_test_server.sh`;
- `scripts/set_s3_test_server_variables.sh`.

The QA repository only coordinates those scripts. It does not copy their implementation and does not invoke the HTTPFS build. The job starts the Python HTTP server, Squid, and the upstream MinIO/S3 test environment, then stops them through the runner cleanup trap.

Tests requiring public-cloud credentials that are not present in GitHub Actions remain governed by the upstream `require-env` conditions.

### DuckLake

- Repository: `duckdb/ducklake`
- Commit: `d318a545571d7d46eb751fa2aa5f6f4389285d3c`
- Selection: `test/*`

DuckLake runs four profiles through the same shared `unittest` binary:

1. the default DuckDB catalog suite;
2. the dedicated filesystem-autoloading test with HTTPFS initially unloaded;
3. the upstream `test/configs/sqlite.json` suite with `sqlite_scanner`;
4. the upstream `test/configs/postgres.json` suite with `postgres_scanner` and a temporary PostgreSQL 15 container.

The upstream SQLite and PostgreSQL JSON files are reused directly. A small helper only enables dynamic extension loading and appends the preinstalled extension set; upstream `on_init`, `test_env`, skip lists, and expected behavior remain unchanged.

HTTPFS, DuckLake, and MSSQL are loaded together in the normal DuckLake profiles.

### MSSQL

- Repository: `hugr-lab/mssql-extension`
- Release tag: `v0.2.1`
- Community version: `0.2.1`
- Selection: `test/sql/*`
- Service: SQL Server 2022

MSSQL deliberately follows a published release tag rather than `main`. This keeps the source tests reproducible and aligned with the binary installed by:

```sql
INSTALL mssql FROM community;
```

The MSSQL job reuses the pinned release's own assets:

- `docker/docker-compose.yml` to start SQL Server 2022;
- `docker/init/init.sql`;
- `docker/init/init-transaction-tests.sql`;
- `scripts/ci/integration_test.sh` for the official smoke test;
- the complete `test/sql/*` SQLLogicTest folder.

The `v0.2.1` integration script only performs the smoke test, so this repository then runs the release's complete SQLLogicTest folder with the shared DuckDB `unittest` binary. The job fails when `require mssql` or mandatory SQL Server connection variables are skipped, preventing a false green run.

The upstream GitHub Actions workflow is not called directly because it is not exposed through `workflow_call`, builds its own DuckDB, and would no longer test the same shared runtime used by HTTPFS and DuckLake. We reuse its service and test contract instead.

#### Updating MSSQL

A maintainer or AI must not replace `v0.2.1` with `main`. To adopt a newer upstream release:

1. find the newest published `hugr-lab/mssql-extension` release tag;
2. verify `duckdb/community-extensions` references the same tag/version;
3. update `.github/workflows/extension-qa.yml` and `config/extensions.yml` together;
4. inspect whether the new release changed its Docker, seed, or integration scripts;
5. keep consuming those files from the pinned checkout instead of copying them locally.

Advancing the release tag is the intentional mechanism through which new upstream tests enter this repository.

## Files

```text
CMakeLists.txt                         minimal qa_test extension build
extension_config.cmake                registers only qa_test
Makefile                               DuckDB extension-template build
scripts/build.sh                       common build and artifact creation
scripts/install-extensions.sql         one-time compatibility-set installation
scripts/init-extensions.sql            full normal initialization
scripts/init-ducklake-default.sql      default DuckLake catalog profile
scripts/init-ducklake-autoload.sql     DuckLake HTTPFS-autoload profile
scripts/init-without-httpfs.sql        HTTPFS autoloading profile
scripts/prepare-ducklake-config.py     adapts pinned upstream catalog configs
scripts/run-tests.sh                   HTTPFS/DuckLake preflight and runner
scripts/run-mssql-tests.sh             pinned MSSQL + SQL Server test runner
scripts/setup-httpfs.sh                coordinates pinned upstream HTTPFS scripts
.github/workflows/extension-qa.yml
config/extensions.yml                  pinned revisions, tags, and test folders
```

## CI triggers

The workflow runs on unfiltered:

- `push`;
- `pull_request`;
- `workflow_dispatch`.

It can therefore be tested from any branch.

## Adding another extension

The current POC remains intentionally explicit. Add another parallel matrix entry only after its repository, pinned release or commit, test folder, and required services are understood. Every battery must continue to install and load the complete supported extension set.
