# Research: HTTPFS and DuckLake CI POC

**Feature**: `001-httpfs-qa-infrastructure`  
**Date**: 2026-07-20

## Decision 1: reuse the extension-template build

The earlier FTS POC showed that the smallest practical build path is the normal DuckDB extension-template flow. The repository therefore contains one trivial local extension, `qa_test`, and runs `make release` through `extension-ci-tools`.

This produces a matching DuckDB CLI, `unittest`, and local extension output without creating a separate build framework.

HTTPFS and DuckLake are not placed in `extension_config.cmake`; they are installed as official binaries at test time.

## Decision 2: pin the revisions declared by DuckDB v1.5.4

DuckDB `v1.5.4` declares:

- HTTPFS commit `c3f215ab360f04dc3d3d5305fa81849c0121f111`;
- DuckLake commit `d318a545571d7d46eb751fa2aa5f6f4389285d3c`.

The CI checks out those revisions for tests and fixtures.

## Decision 3: always load both extensions

Each test job uses a clean HOME, preinstalls both extensions, verifies them with `duckdb_extensions()`, and generates a DuckDB test config that loads both HTTPFS and DuckLake for database restarts and new connections.

This is the central compatibility check: the owner test changes, but the loaded extension set does not.

## Decision 4: start only services needed by the selected test

The first HTTPFS test requires only `PYTHON_HTTP_SERVER_URL` and `PYTHON_HTTP_SERVER_DIR`. The job therefore starts a Python HTTP server following the upstream workflow convention.

Squid and MinIO are intentionally deferred. They will be added directly to the HTTPFS job when a selected upstream test requires them, preferably by reusing the upstream scripts.

The first DuckLake test is local and needs no service.

## Decision 5: avoid testing the QA harness

The first version has no manifest schema, adapter registry, QA unit-test suite, custom result model, or generalized evidence framework. GitHub Actions exit codes and uploaded logs are sufficient for the POC.

A reusable abstraction should be extracted only after multiple real extension jobs repeat the same logic.
