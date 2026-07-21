# CI Architecture

## Objective

Validate DuckDB `v1.5.4` with HTTPFS, DuckLake, and the community MSSQL extension loaded together, using a build-once/fan-out workflow.

## Pipeline

```text
Build DuckDB + unittest + qa_test
                 │
         one shared artifact
                 │
       ┌─────────┼─────────┐
       ▼         ▼         ▼
 HTTPFS test/*  DuckLake   MSSQL test/sql/*
                test/*          │
                           SQL Server 2022
```

There is no generated matrix, adapter framework, or aggregation job. Each extension keeps explicit setup because its upstream contract is materially different.

## Build boundary

The extension-template build compiles:

- DuckDB CLI;
- DuckDB `unittest`;
- the local no-op `qa_test` extension.

It does not compile HTTPFS, DuckLake, or MSSQL. The selected binaries are installed into an isolated `HOME`; MSSQL is installed from DuckDB Community.

The build job packages one artifact:

```text
bin/duckdb
bin/unittest
extensions/qa_test*.duckdb_extension
logs/build-info.txt
```

## Test matrix

The workflow contains three explicit entries:

```text
httpfs
Ducklake
mssql
```

All jobs depend on the same build and therefore run in parallel after it succeeds.

Every job:

1. checks out the owning upstream repository at its pinned commit or release tag;
2. downloads the shared artifact;
3. creates a clean `HOME` and temporary directory;
4. installs and loads the complete compatibility set;
5. verifies the installed/loaded inventory through `duckdb_extensions()`;
6. starts any upstream-required services;
7. runs the pinned upstream test selection;
8. uploads generated configs, extension inventory, service logs, metadata, and test output.

## Common extension runtime

Every normal battery includes:

```sql
INSTALL httpfs;
INSTALL ducklake;
INSTALL mssql FROM community;

LOAD httpfs;
LOAD ducklake;
LOAD mssql;
```

Additional official test dependencies (`json`, `tpch`, `tpcds`, `icu`, `postgres_scanner`, and `sqlite_scanner`) are installed as binaries rather than compiled here.

New test connections reload the appropriate profile. Lifecycle tests that intentionally require HTTPFS to start unloaded use dedicated init profiles, while MSSQL remains loaded because it is outside the lifecycle behavior being asserted.

## HTTPFS setup

The HTTPFS job deliberately reuses scripts from the pinned HTTPFS checkout rather than maintaining copies:

```text
scripts/run_squid.sh
scripts/generate_presigned_url.sh
scripts/run_s3_test_server.sh
scripts/set_s3_test_server_variables.sh
```

The QA-owned `scripts/setup-httpfs.sh` coordinates those scripts, starts the Python HTTP server, waits for local readiness, and exposes their environment variables.

The common runner captures MinIO logs and removes MinIO, Squid, and the Python server through its cleanup trap. Tests requiring unavailable public-cloud credentials remain controlled by the upstream `require-env` declarations.

## DuckLake setup

The DuckLake job uses the pinned upstream repository and runs:

- the default DuckDB-catalog suite;
- the dedicated HTTPFS-autoloading test;
- the upstream SQLite catalog config;
- the upstream PostgreSQL catalog config with PostgreSQL 15.

The upstream config files, skip lists, environment definitions, and init behavior remain authoritative.

## MSSQL setup

MSSQL is pinned to the latest deliberately adopted published release tag, currently `v0.2.1`. The job does not follow `main`.

The source/test checkout and community binary must report the same release version. The runner reuses these files from the tag:

```text
docker/docker-compose.yml
docker/init/init.sql
docker/init/init-transaction-tests.sql
scripts/ci/integration_test.sh
test/sql/*
```

SQL Server 2022 is started from the upstream Compose file. The upstream seed SQL is copied into that container and executed with its bundled `sqlcmd`. The release integration script supplies the official smoke test, and the shared `unittest` binary executes the complete SQLLogicTest folder.

The upstream GitHub Actions workflow is not invoked directly because it is not reusable through `workflow_call` and would build another DuckDB runtime. Reusing its checked-in service/test assets preserves the upstream behavior while testing the same artifact used by HTTPFS and DuckLake.

### Release-update contract for maintainers and AI agents

Never replace the MSSQL release tag with `main` or another moving reference. When adopting a new release:

1. verify the release is published by `hugr-lab/mssql-extension`;
2. verify `duckdb/community-extensions` references the same tag and version;
3. update the workflow and `config/extensions.yml` together;
4. inspect changes to upstream Docker, seed, and integration scripts;
5. continue consuming those files from the pinned checkout instead of copying them locally.

This explicit pin advancement is how new upstream tests enter the compatibility battery.

## Branch policy

The workflow uses unfiltered `push`, `pull_request`, and `workflow_dispatch` triggers. It contains no branch-name filters.

## Evolution rule

Keep extension-specific setup explicit. Extract a reusable abstraction only after at least two real test jobs repeat the same non-trivial setup.
