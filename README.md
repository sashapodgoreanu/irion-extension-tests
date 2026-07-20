# Irion DuckDB Extension Compatibility POC

This repository checks whether the DuckDB extensions used together by Irion remain compatible with a selected DuckDB release.

The first version intentionally follows a small POC design.

## What is built

GitHub Actions uses the normal DuckDB extension-template build to compile:

- DuckDB `v1.5.4`;
- DuckDB `unittest`;
- one trivial local extension named `qa_test`.

`qa_test` exists only to drive the standard build. HTTPFS, DuckLake, and the other official extensions are downloaded rather than compiled here.

## Workflow

```text
                  build
        DuckDB + unittest + qa_test
                    │
             shared artifact
                    │
             ┌──────┴──────┐
             ▼             ▼
       HTTPFS tests   DuckLake tests
         test/*          test/*
```

The two test jobs run in parallel and download the same build artifact.

## Extension bootstrap

Every job uses a clean `HOME` and installs the official extensions once through `scripts/install-extensions.sql`:

```sql
INSTALL json;
INSTALL tpch;
INSTALL tpcds;
INSTALL icu;
INSTALL httpfs;
INSTALL ducklake;
INSTALL postgres_scanner;
INSTALL sqlite_scanner;
```

Normal test databases load the required extensions through init scripts. Additional connections reload the same profile through `on_new_connection`.

The runner prints `duckdb_extensions()` before the tests and fails when a required extension is missing, not loaded, or still appears in the skipped-test summary.

## Complete upstream test folders

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

DuckLake runs three profiles through the same shared `unittest` binary:

1. the default DuckDB catalog suite;
2. the upstream `test/configs/sqlite.json` suite with `sqlite_scanner`;
3. the upstream `test/configs/postgres.json` suite with `postgres_scanner` and a temporary PostgreSQL 15 container.

The upstream SQLite and PostgreSQL JSON files are reused directly. A small helper only enables dynamic extension loading and appends the preinstalled extension set; upstream `on_init`, `test_env`, skip lists, and expected behavior remain unchanged.

HTTPFS and DuckLake are loaded in every DuckLake profile.

## Files

```text
CMakeLists.txt                         minimal qa_test extension build
extension_config.cmake                registers only qa_test
Makefile                               DuckDB extension-template build
scripts/build.sh                       common build and artifact creation
scripts/install-extensions.sql         one-time official extension installation
scripts/init-extensions.sql            full normal initialization
scripts/init-ducklake-default.sql      default DuckLake catalog profile
scripts/init-without-httpfs.sql        HTTPFS autoloading profile
scripts/prepare-ducklake-config.py     adapts pinned upstream catalog configs
scripts/run-tests.sh                   preflight, services, and unittest runner
scripts/setup-httpfs.sh                coordinates pinned upstream HTTPFS scripts
.github/workflows/extension-qa.yml
config/extensions.yml                  pinned revisions and complete test folders
```

## CI triggers

The workflow runs on unfiltered:

- `push`;
- `pull_request`;
- `workflow_dispatch`.

It can therefore be tested from any branch.

## Adding another extension

The current POC remains intentionally explicit. Add another parallel matrix entry only after its repository, pinned commit, test folder, and required services are understood. Every battery must continue to install and load the complete supported extension set.
