# Irion DuckDB Extension QA Constitution

## Core principles

### I. Keep the harness small

This repository is a compatibility POC, not a framework product. Prefer a small number of explicit scripts and GitHub Actions jobs over generic schemas, adapter registries, result models, or tests of the QA platform itself.

### II. One local extension may drive the DuckDB build

The repository MAY contain and compile one minimal local extension named `qa_test`. Its only purpose is to reuse the standard DuckDB extension-template build and produce a matching DuckDB CLI and `unittest` binary.

The local extension MUST remain trivial and MUST NOT contain product functionality. HTTPFS, DuckLake, and every extension under compatibility test MUST NOT be compiled by this repository.

### III. Build once, test in parallel

For each DuckDB target, CI MUST build DuckDB, `unittest`, and `qa_test` once. The resulting build artifact MUST be downloaded by parallel extension test jobs. Test jobs MUST NOT rebuild DuckDB.

### IV. Always load the complete compatibility set

Every test job MUST use an isolated HOME and execute, in this order:

```sql
INSTALL httpfs;
INSTALL ducklake;
LOAD httpfs;
LOAD ducklake;
```

A failed install or load MUST fail the job before upstream tests run. The extension inventory MUST be printed to the job log.

### V. Use upstream tests and setup

HTTPFS and DuckLake repositories MUST be checked out at the immutable commits declared by DuckDB `v1.5.4`. Tests MUST run directly from those checkouts with DuckDB `unittest --test-dir`.

When a test needs services, the test job SHOULD reuse the setup approach or scripts from the extension's own CI. Service setup remains in that test job and MUST be cleaned up with a shell trap.

### VI. CI from every branch

The workflow MUST support unfiltered `push`, `pull_request`, and `workflow_dispatch`. It MUST NOT contain literal branch filters.

### VII. First version scope

The first version contains only:

- the minimal `qa_test` extension;
- one shared Linux build job for DuckDB `v1.5.4`;
- one HTTPFS test job;
- one DuckLake test job;
- one common runner that always installs and loads HTTPFS and DuckLake;
- small build/test logs uploaded by GitHub Actions.

Manifest schemas, adapter frameworks, QA unit tests, result classification frameworks, generalized service registries, and aggregated reporting are out of scope until repeated real use demonstrates a need.

## Governance

Changes should preserve the smallest implementation that runs the real compatibility tests. New abstraction requires at least two concrete extension workflows that benefit from it.

**Version**: 2.0.0 | **Ratified**: 2026-07-20 | **Last Amended**: 2026-07-20
