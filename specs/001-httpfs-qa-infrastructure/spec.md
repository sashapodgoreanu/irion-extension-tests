# Feature Specification: HTTPFS and DuckLake CI POC

**Feature Branch**: `001-httpfs-qa-infrastructure`  
**Created**: 2026-07-20  
**Status**: Implementation

## Goal

Create a small GitHub Actions POC inspired by the earlier FTS CI approach:

1. build DuckDB `v1.5.4`, its `unittest` runner, and one trivial local extension named `qa_test`;
2. publish that build once as a workflow artifact;
3. run HTTPFS and DuckLake upstream test subsets in parallel;
4. install and load both `httpfs` and `ducklake` before every test subset;
5. start HTTPFS test infrastructure inside the HTTPFS job by reusing the upstream CI setup where practical.

The repository must test extension compatibility, not create a framework that itself needs a large unit-test suite.

## User stories

### US1 — Build the common DuckDB runtime

As an engineer, I can run one build job that uses the standard DuckDB extension-template tooling to compile a minimal `qa_test` extension together with DuckDB and `unittest`.

**Acceptance**:

- DuckDB and `extension-ci-tools` are pinned to `v1.5.4`.
- The build includes only the local `qa_test` extension; HTTPFS and DuckLake are not compiled.
- The artifact contains the DuckDB CLI and `unittest` needed by test jobs.
- The build occurs once.

### US2 — Run HTTPFS and DuckLake tests in parallel

As an engineer, I can run two independent jobs from the same build artifact.

**Acceptance**:

- both jobs use isolated HOME directories;
- both jobs execute `INSTALL/LOAD httpfs` and `INSTALL/LOAD ducklake` before tests;
- the HTTPFS job checks out `duckdb-httpfs` at `c3f215ab360f04dc3d3d5305fa81849c0121f111`;
- the DuckLake job checks out `ducklake` at `d318a545571d7d46eb751fa2aa5f6f4389285d3c`;
- each job runs at least one original SQLLogicTest through `unittest --test-dir`;
- the jobs run in parallel after the common build.

### US3 — Use HTTPFS upstream infrastructure

As an engineer, I can run the selected HTTPFS test with the service setup expected by upstream.

**Acceptance**:

- the first HTTPFS subset uses the upstream Python HTTP-server convention;
- service startup and cleanup are implemented directly in the HTTPFS job or a small dedicated script;
- containers such as MinIO are added only when the selected HTTPFS subset requires them;
- no generic adapter framework is introduced.

### US4 — Run from any branch

As a contributor, I can trigger the workflow from any branch.

**Acceptance**:

- triggers are unfiltered `push`, `pull_request`, and `workflow_dispatch`;
- no literal branch-name conditions are present.

## Functional requirements

- **FR-001**: The repository MUST contain a minimal local `qa_test` DuckDB extension used only to drive the standard extension build.
- **FR-002**: The build MUST produce DuckDB CLI and `unittest` exactly once per target.
- **FR-003**: HTTPFS and DuckLake MUST NOT be compiled by this repository.
- **FR-004**: Every test job MUST install and load HTTPFS and DuckLake in the same isolated runtime.
- **FR-005**: A failed installation or load MUST stop the job before upstream tests execute.
- **FR-006**: HTTPFS and DuckLake source checkouts MUST use immutable commits associated with DuckDB `v1.5.4`.
- **FR-007**: Tests MUST execute directly from upstream checkouts with `unittest --test-dir`.
- **FR-008**: The first HTTPFS test is `test/sql/curl_client/test_relative_path_parsing.test` and uses a local Python HTTP server.
- **FR-009**: The first DuckLake test is `test/sql/ducklake_basic.test`.
- **FR-010**: HTTPFS and DuckLake test jobs MUST run in parallel using the same build artifact.
- **FR-011**: The workflow MUST be eligible on any branch.
- **FR-012**: The implementation MUST remain explicit and small; schemas, adapter registries, QA-platform tests, and generalized reporting are not part of this version.

## Success criteria

- One successful build artifact is reused by both test jobs.
- `duckdb_extensions()` shows `httpfs` and `ducklake` as installed and loaded in both jobs.
- The selected HTTPFS and DuckLake tests are executed from their original repositories.
- No HTTPFS or DuckLake build target is present.
- The workflow contains no branch filter.
