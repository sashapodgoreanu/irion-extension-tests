# CI Architecture

## Objective

Validate DuckDB `v1.5.4` with HTTPFS and DuckLake loaded together, using a small build-once/fan-out workflow.

## Pipeline

```text
Build DuckDB + unittest + qa_test
                │
        one shared artifact
                │
        ┌───────┴────────┐
        ▼                ▼
 HTTPFS test/*     DuckLake test/*
```

There is no configuration-validation job, generated matrix, adapter framework, or aggregation job in the first version.

## Build boundary

The extension-template build compiles:

- DuckDB CLI;
- DuckDB `unittest`;
- the local no-op `qa_test` extension.

It does not compile HTTPFS or DuckLake. Those extensions do not appear in `extension_config.cmake`.

The build job packages one artifact:

```text
bin/duckdb
bin/unittest
extensions/qa_test*.duckdb_extension
logs/build-info.txt
```

## Test matrix

The workflow contains two explicit entries:

```text
httpfs
ducklake
```

Both jobs depend on the same build and therefore run in parallel after it succeeds.

Each job:

1. checks out the owning upstream repository and its submodules at the pinned commit;
2. downloads the shared artifact;
3. creates a clean HOME and temporary directory;
4. installs and loads HTTPFS and DuckLake;
5. verifies both through `duckdb_extensions()`;
6. runs the complete upstream `test/*` selection with `unittest --test-dir`;
7. uploads the generated configuration, extension inventory, service logs, test metadata, and test output.

## Common extension runtime

Every battery uses the same initialization:

```sql
INSTALL httpfs;
INSTALL ducklake;
LOAD httpfs;
LOAD ducklake;
```

The DuckDB test configuration reloads `httpfs` and `ducklake` whenever a test creates a new database. A failure to install or load either extension stops the job before the upstream suite runs.

`json` and `tpch` are installed as official binaries because the HTTPFS upstream integration workflow uses them for its complete test profile and fixture generation. They are not compiled by this repository.

## HTTPFS setup

The HTTPFS job deliberately reuses scripts from the pinned HTTPFS checkout rather than maintaining copies:

```text
scripts/run_squid.sh
scripts/generate_presigned_url.sh
scripts/run_s3_test_server.sh
scripts/set_s3_test_server_variables.sh
```

The QA-owned `scripts/setup-httpfs.sh` only coordinates those scripts, starts the Python HTTP server, waits for local readiness, and exposes their environment variables.

The common runner's EXIT trap:

- captures MinIO logs;
- stops and removes the MinIO Compose project;
- stops Squid;
- stops the Python HTTP server.

Tests requiring unavailable public-cloud credentials remain controlled by the upstream `require-env` declarations.

## DuckLake setup

The DuckLake job runs the complete pinned `test/*` folder with its original fixtures, submodules, and relative paths. No additional QA-owned service layer is introduced.

## Branch policy

The workflow uses unfiltered `push`, `pull_request`, and `workflow_dispatch` triggers. It contains no branch-name filters.

## Evolution rule

Keep extension-specific setup explicit. Extract a reusable abstraction only after at least two real test jobs repeat the same non-trivial setup.
