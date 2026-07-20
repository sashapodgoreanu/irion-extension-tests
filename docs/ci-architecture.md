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
 HTTPFS upstream    DuckLake upstream
      test                test
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

1. checks out the owning upstream repository at its pinned commit;
2. downloads the shared artifact;
3. creates a clean HOME and temporary directory;
4. installs and loads HTTPFS and DuckLake;
5. verifies both through `duckdb_extensions()`;
6. runs one upstream SQLLogicTest with `unittest --test-dir`;
7. uploads the generated configuration, extension inventory, test metadata, and test output.

## Common extension runtime

Every battery uses the same initialization:

```sql
INSTALL httpfs;
INSTALL ducklake;
LOAD httpfs;
LOAD ducklake;
```

The DuckDB test configuration also reloads `httpfs` and `ducklake` for database restarts and new connections. A failure to install or load either extension stops the job before the upstream test runs.

## HTTPFS setup

The first HTTPFS test requires only a local Python HTTP server. `scripts/setup-httpfs.sh` exports the environment variables used by upstream:

```text
PYTHON_HTTP_SERVER_URL
PYTHON_HTTP_SERVER_DIR
```

The server runs only in the HTTPFS job and is stopped by the common runner's EXIT trap. Its log is uploaded with the HTTPFS test evidence.

Squid and MinIO are intentionally absent from the first version. They can be added directly to the HTTPFS job when a selected upstream test needs them, following the upstream HTTPFS workflow.

## DuckLake setup

The initial DuckLake test uses a local metadata database and data directory. It requires no external container.

## Branch policy

The workflow uses unfiltered `push`, `pull_request`, and `workflow_dispatch` triggers. It contains no branch-name filters.

## Evolution rule

Keep extension-specific setup explicit. Extract a reusable abstraction only after at least two real test jobs repeat the same non-trivial setup.
