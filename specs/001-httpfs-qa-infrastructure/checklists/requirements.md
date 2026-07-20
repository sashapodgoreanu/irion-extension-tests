# Specification Checklist: HTTPFS and DuckLake CI POC

**Feature**: [HTTPFS and DuckLake CI POC](../spec.md)  
**Date**: 2026-07-20

## Scope

- [x] The feature is a small compatibility POC, not a reusable QA framework.
- [x] `qa_test` is the only extension compiled locally.
- [x] HTTPFS and DuckLake are installed from the official DuckDB extension repository.
- [x] Manifest schemas, adapter registries, custom result models, and tests of the QA platform are out of scope.

## Build and execution

- [x] DuckDB `v1.5.4` and extension-ci-tools `v1.5.4` are pinned.
- [x] One build job produces DuckDB CLI, `unittest`, and `qa_test`.
- [x] HTTPFS and DuckLake test jobs reuse the same artifact.
- [x] The two test jobs run in parallel.
- [x] Both jobs use isolated HOME and temporary directories.

## Extension compatibility

- [x] Every battery executes `INSTALL httpfs` and `INSTALL ducklake`.
- [x] Every battery executes `LOAD httpfs` and `LOAD ducklake`.
- [x] Both extensions are verified through `duckdb_extensions()` before upstream tests.
- [x] Installation or loading failure stops the job.

## Upstream tests

- [x] HTTPFS tests are pinned to `c3f215ab360f04dc3d3d5305fa81849c0121f111`.
- [x] DuckLake tests are pinned to `d318a545571d7d46eb751fa2aa5f6f4389285d3c`.
- [x] Tests run directly from their upstream checkout using `unittest --test-dir`.
- [x] The HTTPFS subset uses the upstream Python HTTP-server environment convention.
- [x] Squid and MinIO are deferred until a selected test needs them.

## Workflow

- [x] The workflow has unfiltered `push`, `pull_request`, and `workflow_dispatch` triggers.
- [x] No literal branch filter is present.
- [x] Standard GitHub Actions logs and artifacts are used instead of a custom reporting layer.

## Runtime verification

- [ ] A GitHub Actions run has completed successfully on the feature branch.
- [ ] Both job logs confirm HTTPFS and DuckLake are loaded together.
