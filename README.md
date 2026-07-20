# Irion DuckDB Extension Compatibility POC

This repository checks whether the DuckDB extensions used together by Irion remain compatible with a selected DuckDB release.

The first version intentionally follows a small POC design.

## What is built

GitHub Actions uses the normal DuckDB extension-template build to compile:

- DuckDB `v1.5.4`;
- DuckDB `unittest`;
- one trivial local extension named `qa_test`.

`qa_test` exists only to drive the standard build. HTTPFS and DuckLake are not compiled here.

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

## Shared extension initialization

Every job uses [`scripts/init-extensions.sql`](scripts/init-extensions.sql) as the DuckDB `unittest` `init_script`.

The script installs and loads the official repository extensions required by the two complete upstream suites:

```sql
INSTALL json;
INSTALL tpch;
INSTALL icu;
INSTALL httpfs;
INSTALL ducklake;

LOAD json;
LOAD tpch;
LOAD icu;
LOAD httpfs;
LOAD ducklake;
```

The same script is executed by the preflight CLI and by every test database created by `unittest`. Additional test connections reload the same extensions through `on_new_connection`.

The test configuration uses `autoloading: all` so SQLLogicTest directives such as `require httpfs`, `require ducklake`, `require json`, and `require tpch` recognize the dynamically installed extensions. The runner fails if any of these extension requirements still appears in the skipped-test summary.

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

DuckLake tests use their original checkout, fixtures, submodules, and relative paths. They run through the same shared `unittest` binary with both DuckLake and HTTPFS loaded.

## Files

```text
CMakeLists.txt                 minimal qa_test extension build
extension_config.cmake        registers only qa_test
Makefile                       DuckDB extension-template build
scripts/build.sh               common build and artifact creation
scripts/init-extensions.sql    shared INSTALL/LOAD initialization
scripts/run-tests.sh           common preflight and unittest runner
scripts/setup-httpfs.sh        coordinates pinned upstream HTTPFS scripts
.github/workflows/extension-qa.yml
config/extensions.yml          pinned revisions and complete test folders
```

## CI triggers

The workflow runs on unfiltered:

- `push`;
- `pull_request`;
- `workflow_dispatch`.

It can therefore be tested from any branch.

## Adding another extension

The current POC remains intentionally explicit. Add another parallel matrix entry only after its repository, pinned commit, test folder, and required services are understood. Every battery must continue to install and load the complete supported extension set.
