# Implementation Plan: HTTPFS and DuckLake CI POC

**Branch**: `001-httpfs-qa-infrastructure`  
**DuckDB**: `v1.5.4`

## Approach

Use the same simple shape as the earlier FTS POC:

1. restore one trivial local extension named `qa_test`;
2. use DuckDB extension-template tooling to build `qa_test`, DuckDB CLI, and `unittest` once;
3. upload the build output;
4. start two parallel jobs, one for HTTPFS and one for DuckLake;
5. install and load `httpfs` and `ducklake` before every test run;
6. execute original tests directly from pinned upstream checkouts.

The first version does not include a manifest schema, adapter registry, tests for the QA platform, result models, or generalized reporting.

## Pinned inputs

- DuckDB: `v1.5.4`
- extension-ci-tools: `v1.5.4`
- HTTPFS: `duckdb/duckdb-httpfs@c3f215ab360f04dc3d3d5305fa81849c0121f111`
- DuckLake: `duckdb/ducklake@d318a545571d7d46eb751fa2aa5f6f4389285d3c`

## Build

The repository contains `CMakeLists.txt`, `extension_config.cmake`, `Makefile`, and the small `qa_test` source. HTTPFS and DuckLake are not present in the CMake extension configuration and are never compiled.

The build job checks out the DuckDB and extension-ci-tools submodules at `v1.5.4`, runs the normal release build, builds `unittest`, and uploads one artifact containing the release outputs.

## Parallel tests

Both jobs download the same artifact and use an isolated HOME. Before upstream tests, both execute:

```sql
INSTALL httpfs;
INSTALL ducklake;
LOAD httpfs;
LOAD ducklake;
```

The job then prints `duckdb_extensions()` and runs its own upstream test with `unittest --test-dir`.

Initial subsets:

- HTTPFS: `test/sql/curl_client/test_relative_path_parsing.test`
- DuckLake: `test/sql/ducklake_basic.test`

The HTTPFS job starts a Python HTTP server using the variable names from the upstream HTTPFS workflow. Squid and MinIO are added later only when a selected test requires them.

## Workflow

`.github/workflows/extension-qa.yml` contains:

- unfiltered `push`, `pull_request`, and `workflow_dispatch` triggers;
- one build job;
- one two-entry test matrix that fans out after the build;
- normal GitHub log and artifact upload.

## Implementation order

1. Restore `qa_test`.
2. Replace FTS configuration with HTTPFS and DuckLake.
3. Add one build script.
4. Add one common test runner.
5. Add one HTTPFS setup script.
6. Add the GitHub Actions workflow.
7. Run CI and fix concrete failures.
