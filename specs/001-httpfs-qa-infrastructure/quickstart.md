# Quickstart: HTTPFS and DuckLake CI POC

## Run it

Push this branch, open a pull request, or use `workflow_dispatch`. The workflow has no branch filters.

## Expected jobs

```text
Build DuckDB and qa_test
          │
          ├───────────────┐
          ▼               ▼
   Test httpfs      Test ducklake
```

There is one build artifact and two parallel consumers.

## Build output

The shared artifact contains:

```text
bin/duckdb
bin/unittest
extensions/qa_test*.duckdb_extension
logs/build-info.txt
```

`qa_test` is the only extension built locally. HTTPFS, DuckLake, and test dependencies are installed from the official DuckDB extension repository.

## Runtime check

Both test jobs must print two successful rows from `duckdb_extensions()` after running:

```sql
INSTALL httpfs;
INSTALL ducklake;
LOAD httpfs;
LOAD ducklake;
```

## HTTPFS job

The job checks out:

```text
duckdb/duckdb-httpfs@c3f215ab360f04dc3d3d5305fa81849c0121f111
```

It executes the complete selection:

```text
test/*
```

Before the suite starts, it reuses the pinned upstream scripts for Squid, fixture generation, MinIO/S3 variables, and S3 startup. A local Python HTTP server is started by the small QA coordinator script.

## DuckLake job

The job checks out:

```text
duckdb/ducklake@d318a545571d7d46eb751fa2aa5f6f4389285d3c
```

It executes the complete selection:

```text
test/*
```

## Failure diagnosis

- Build failure: inspect the `Build DuckDB and qa_test` log.
- Install/load failure: inspect `extensions.csv` in the job log artifact.
- HTTPFS service failure: inspect `services/python-http.log`, `services/squid-process.log`, and `services/minio.log`.
- SQLLogicTest failure: inspect `unittest.log` for that matrix job.

No separate QA-platform validation or result-classification framework is involved.
