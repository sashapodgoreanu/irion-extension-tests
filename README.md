# Irion DuckDB Extension QA

Quality-assurance harness for the complete set of DuckDB extensions used by Irion.

This repository is intentionally **not a DuckDB extension**. It may reuse DuckDB CI tooling, but it does not implement, compile, package, or distribute extension code.

> **The only native software compiled by this repository is DuckDB itself and its `unittest` runner.**

The governing rules are defined in [the project Constitution](.specify/memory/constitution.md).

## Purpose

When Irion upgrades DuckDB, every declared extension must continue to work while all other Irion extensions are present in the same DuckDB runtime.

An extension may pass its own isolated CI and still fail when loaded together with other extensions because of:

- function, type, or setting-name collisions;
- incompatible global initialization;
- filesystem, catalog, or secret-provider conflicts;
- load-order dependencies;
- binary or dependency incompatibilities;
- behavior changes introduced by a DuckDB upgrade.

This repository tests the complete Irion extension composition rather than isolated extensions.

## Execution model

```text
config/extensions.yml
        │
        ├── extension name
        ├── test repository
        ├── immutable test commit SHA
        ├── INSTALL / LOAD statements
        ├── upstream test paths
        └── optional infrastructure adapter
                    │
                    ▼
         Build DuckDB + unittest once
                    │
                    ▼
          Publish shared build artifact
                    │
          ┌─────────┼─────────┬──────────────┐
          ▼         ▼         ▼              ▼
       FTS tests  Spatial   Iceberg      PostgreSQL tests
                    tests     tests       + PostgreSQL service
          │         │         │              │
          └─────────┴─────────┴──────────────┘
                    │
                    ▼
      Every job INSTALLs and LOADs every enabled extension
```

DuckDB is built once for each platform/build configuration. After that build succeeds, each extension-owned test group runs in a separate parallel CI job using the same DuckDB artifact.

The test group selects which upstream tests to execute. It does **not** select which extensions are loaded: every enabled extension is installed and loaded before every group.

## What is compiled

The build stage compiles only:

```text
DuckDB CLI
DuckDB unittest
```

The build stage must not contain:

```text
extension source checkouts
extension CMake configurations
static extension targets
loadable extension targets
extension-owned native dependencies
locally built .duckdb_extension files
```

Extensions are installed as prebuilt binaries with their declared statements, normally:

```sql
INSTALL fts;
LOAD fts;
```

## Upstream tests

Tests are never copied into this repository.

For every extension, CI checks out its repository at the commit declared in `config/extensions.yml` and executes the original tests from that checkout. SQLLogicTests are passed to DuckDB through an external test directory:

```bash
unittest \
  --test-config generated/all-extensions-loaded.json \
  --test-dir upstream/fts \
  "test/sql/fts/*"
```

Fixtures and relative paths remain exactly as they are in the extension repository.

## Adding an extension

1. Add an entry to [`config/extensions.yml`](config/extensions.yml).
2. Pin the test repository to an immutable commit SHA.
3. Declare how the prebuilt extension is installed and loaded.
4. Declare the upstream test roots and filters.
5. Select `none` as adapter or create an infrastructure adapter.
6. Verify that expected tests are discovered.
7. Verify that all enabled extensions are installed and loaded before the new group runs.
8. Rerun every existing group because the all-loaded runtime has changed.

## Infrastructure adapters

Some upstream test groups need external infrastructure.

A PostgreSQL adapter can, for example:

1. start a pinned PostgreSQL container;
2. wait until it is healthy;
3. create users, databases, and fixtures;
4. generate a connection string;
5. expose the connection string to the upstream PostgreSQL tests;
6. execute those tests using the shared DuckDB `unittest` artifact;
7. keep every enabled DuckDB extension loaded;
8. collect PostgreSQL logs and tear the service down.

Adapters prepare test infrastructure only. They never compile extensions and never rebuild DuckDB.

## Planned structure

```text
.specify/memory/constitution.md   Governing principles
config/extensions.yml            Extension and test-group inventory
config/schema/                    Manifest validation schema
adapters/                         Extension-specific services and fixtures
scripts/                          Validation and CI orchestration
.github/workflows/                Build-once and parallel test workflows
tests/irion/                      Irion-owned cross-extension smoke tests
docs/                             Architecture and operating documentation
```

See [`docs/ci-architecture.md`](docs/ci-architecture.md) for the planned workflow.
