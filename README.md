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
```

The two test jobs run in parallel and download the same build artifact.

Before either battery starts, the runner creates a clean HOME and executes:

```sql
INSTALL httpfs;
INSTALL ducklake;
LOAD httpfs;
LOAD ducklake;
```

Both extensions are therefore present for every test battery, including tests owned by the other extension.

## Initial upstream tests

### HTTPFS

- Repository: `duckdb/duckdb-httpfs`
- Commit: `c3f215ab360f04dc3d3d5305fa81849c0121f111`
- Test: `test/sql/curl_client/test_relative_path_parsing.test`

The job starts the same style of local Python HTTP server used by the upstream HTTPFS integration workflow. Squid and MinIO are not started yet because this first test does not need them.

### DuckLake

- Repository: `duckdb/ducklake`
- Commit: `d318a545571d7d46eb751fa2aa5f6f4389285d3c`
- Test: `test/sql/ducklake_basic.test`

The test creates a local DuckLake catalog and data directory and does not require an external service.

## Files

```text
CMakeLists.txt                 minimal qa_test extension build
extension_config.cmake        registers only qa_test
Makefile                       DuckDB extension-template build
scripts/build.sh               common build and artifact creation
scripts/run-tests.sh           always installs/loads HTTPFS + DuckLake
scripts/setup-httpfs.sh        local Python HTTP server
.github/workflows/extension-qa.yml
config/extensions.yml          pinned versions and first test subsets
```

## CI triggers

The workflow runs on unfiltered:

- `push`;
- `pull_request`;
- `workflow_dispatch`.

It can therefore be tested from any branch.

## Next steps

Broader HTTPFS tests can add Squid or MinIO directly to the HTTPFS job by reusing the upstream setup scripts. General adapter frameworks and tests of the QA infrastructure should only be introduced after multiple real extensions demonstrate the same repeated need.
