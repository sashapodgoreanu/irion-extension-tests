# Implementation Plan: HTTPFS QA Infrastructure

**Branch**: `001-httpfs-qa-infrastructure` | **Date**: 2026-07-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-httpfs-qa-infrastructure/spec.md`

## Summary

Implement the first reusable build-once/fan-out QA pipeline for Irion's DuckDB extension compatibility repository.

The pipeline will compile a standard DuckDB `v1.5.4` distribution and its `unittest` executable once, publish a relocatable artifact, and then run an HTTPFS-owned test group in a separate job. HTTPFS itself will never be compiled by this repository. The test job will install the official prebuilt HTTPFS binary with `INSTALL httpfs`, load it explicitly, provision the HTTPFS integration services, and execute the original SQLLogicTests directly from a pinned `duckdb-httpfs` checkout through `unittest --test-dir`.

The workflow will be generated from the version-controlled extension manifest and will be eligible to run on `push`, `pull_request`, and `workflow_dispatch` from any branch without branch-name filters.

## Technical Context

**Language/Version**: Bash 5.x for orchestration; Python 3.11+ for manifest validation, matrix generation, configuration generation, and report normalization; YAML/JSON for declarative configuration

**Primary Dependencies**:

- DuckDB `v1.5.4`
- `duckdb/extension-ci-tools` `v1.5.4`
- CMake + Ninja + GCC toolchain supplied by the official `linux_amd64` CI container
- GitHub Actions
- Docker Engine and Docker Compose for the HTTPFS S3-compatible service
- Squid for proxy tests
- Python standard-library HTTP server
- pinned Python packages for YAML and JSON Schema validation

**Storage**: Version-controlled YAML/JSON configuration plus ephemeral workflow artifacts, temporary databases, service volumes, logs, and generated test configuration

**Testing**:

- Python unit tests for manifest parsing, validation, matrix rendering, and test-config generation
- contract tests for generated artifact layout, workflow trigger policy, adapter lifecycle, and absence of extension build targets
- GitHub Actions integration test using the pinned HTTPFS upstream suite
- preflight SQL assertions against `duckdb_extensions()`

**Target Platform**: Linux `amd64` on GitHub-hosted `ubuntu-24.04`; build performed with the official DuckDB `linux_amd64` extension CI toolchain container

**Project Type**: CI orchestration and quality-assurance harness

**Performance Goals**:

- exactly one DuckDB build job per platform/build-profile matrix entry
- no DuckDB rebuild in extension test-group jobs
- test groups independently parallelizable after the shared build succeeds
- manifest validation and matrix generation complete in less than one minute under normal GitHub-hosted runner conditions

**Constraints**:

- compile only the standard DuckDB distribution, DuckDB CLI, and `unittest`
- never add HTTPFS or any tested extension source to the DuckDB build graph
- never build local `.duckdb_extension` binaries
- obtain tested extensions only as declared prebuilt binaries
- run upstream tests from pinned source checkouts without copying them
- load the complete enabled extension set before every test group
- use isolated HOME, extension, temporary, database, and secret directories
- fail closed on missing binaries, failed installation/load, empty test discovery, unhealthy services, crashes, timeouts, and unexplained skips
- workflow triggers and conditions must not contain literal branch names

**Scale/Scope**: Initial implementation supports one DuckDB target, one enabled extension (`httpfs`), one HTTPFS integration test group, and one infrastructure adapter. The contracts must scale to dozens of enabled extensions and independently parallel test groups without changing the shared build implementation.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Plan Evidence |
|---|---|---|
| QA harness, not a product extension | PASS | Repository code is orchestration, validation, adapters, and reports only. No extension product source is introduced. |
| Compile DuckDB only | PASS | Build job checks out DuckDB and targets only `duckdb` and `unittest`. No tested extension config or source directory is passed to CMake. DuckDB's upstream mandatory in-tree components remain part of the standard DuckDB distribution and are not Irion test extensions. |
| Declarative and pinned extension inventory | PASS | `config/extensions.yml` remains the single source of truth and is validated against a committed schema. HTTPFS test source is pinned to `c3f215ab360f04dc3d3d5305fa81849c0121f111`. |
| Build DuckDB once, fan out groups | PASS | Dedicated build job publishes one shared artifact consumed by the generated test-group matrix. |
| All declared extensions loaded for every group | PASS | The generated group configuration installs all enabled extensions in an isolated HOME and emits `LOAD` statements for every enabled entry before owner tests run. |
| Upstream test fidelity | PASS | HTTPFS tests, fixtures, and safe infrastructure scripts are used from the pinned upstream checkout through `--test-dir`; nothing is copied into Irion-owned test directories. |
| Extension-specific adapters | PASS | HTTPFS services are encapsulated behind a generic adapter lifecycle and are not part of the DuckDB build job. |
| Fail closed and produce evidence | PASS | Every setup phase has explicit validation and classification; artifacts are uploaded with `if: always()`. |
| Reproducibility and safe evolution | PASS | Sources, CI tooling, actions, packages, and service images are pinned; all writable state is isolated per job. |
| Any-branch workflow | PASS | Workflow contract uses unfiltered `push`, `pull_request`, and `workflow_dispatch`; automated contract tests reject branch filters and hard-coded branch conditions. |

### Post-Design Re-check

The Phase 1 design introduces no Constitution violations. The HTTPFS adapter may install fixture-generation tools such as the official prebuilt `tpch` extension, but it may not compile them and may not add them to the enabled Irion extension set unless they are explicitly declared there. Such tools are adapter-scoped setup dependencies and must be recorded in evidence.

## Architecture

```text
config/extensions.yml
        │
        ▼
validate-manifest job
        │
        ├── validated manifest artifact
        └── generated test-group matrix
                    │
                    ├──────────────────────┐
                    ▼                      │
build-duckdb job                           │
  checkout DuckDB                         │
  build duckdb + unittest only            │
  reject local .duckdb_extension files    │
  publish shared artifact                 │
                    │                      │
                    └──────────┬───────────┘
                               ▼
                  test-group matrix jobs
                               │
                  download DuckDB artifact
                               │
                  checkout owner test repo
                               │
                  create isolated runtime
                               │
                  adapter setup/readiness
                               │
                  INSTALL all enabled extensions
                  LOAD all enabled extensions
                               │
                  discover owner test files
                               │
                  unittest --test-dir <checkout>
                               │
                  normalize results + teardown
                               │
                  publish evidence always
```

## Build Strategy

1. Check out this repository, DuckDB, and `extension-ci-tools` at pinned references.
2. Build the official `linux_amd64` toolchain container from the pinned CI-tools source.
3. Configure DuckDB without an Irion extension configuration and without any external extension source directory.
4. Build only the `duckdb` and `unittest` targets.
5. Scan the build tree and fail if any tested-extension `.duckdb_extension` file exists.
6. Package a relocatable artifact containing:
   - `bin/duckdb`
   - `bin/unittest`
   - required runtime libraries, if any are reported by `ldd`
   - `metadata/build.json`
   - `checksums/SHA256SUMS`
7. Extract the artifact in a clean directory and execute both binaries as a relocation smoke test before upload.

DuckDB `v1.5.4` loads `core_functions` and `parquet` in its upstream base configuration as essential parts of the standard distribution. The implementation must not add HTTPFS or any other tested external extension to this build.

## Test-Group Strategy

Each generated test-group job will:

1. Download and verify the shared DuckDB artifact.
2. Check out the owning extension's test repository at its immutable commit.
3. Create isolated directories for HOME, DuckDB extensions, secrets, temporary files, databases, service state, and reports.
4. Run the selected adapter's setup and readiness phases.
5. Install every enabled extension from its declared prebuilt source into the isolated HOME.
6. Load every enabled extension and verify name, version, installation mode, and source through `duckdb_extensions()`.
7. Generate a DuckDB test config whose initialization loads the complete enabled extension set for each database instance used by `unittest`.
8. Discover tests using the manifest's include/exclude rules and fail if the expected inventory is empty.
9. Execute the owner group's upstream tests through `unittest --test-dir`.
10. Classify the result as success, functional failure, infrastructure failure, timeout, crash, or configuration failure.
11. Run adapter teardown unconditionally and publish evidence unconditionally.

## HTTPFS Adapter Strategy

The HTTPFS adapter will wrap, rather than blindly execute, the pinned upstream integration setup:

- local Python HTTP server on an allocated/tested port;
- Squid proxy with explicit log directory and readiness probe;
- S3-compatible MinIO stack using the pinned upstream Compose definition or an equivalent pinned image contract;
- host aliases required by the upstream MinIO test configuration;
- generated fixtures and presigned URLs;
- environment variables expected by the upstream tests;
- service logs and deterministic teardown.

The adapter must reject commands that invoke `make`, CMake, Ninja, or HTTPFS extension build targets. Safe upstream scripts may be called only after their behavior is validated against the pinned commit.

Fixture generation may use the shared DuckDB CLI and prebuilt setup-only extensions such as `tpch`. Setup-only extensions must be installed dynamically, recorded in metadata, and must not be mistaken for enabled Irion compatibility extensions.

## Workflow Trigger Contract

The workflow must have the semantic equivalent of:

```yaml
on:
  push:
  pull_request:
  workflow_dispatch:
```

It must not contain `branches`, `branches-ignore`, literal branch comparisons, branch-specific paths, or branch-derived artifact names. Concurrency may use dynamic workflow/ref/event identifiers.

GitHub Actions and reusable actions must be pinned to immutable commit SHAs in the implementation.

## Project Structure

### Documentation (this feature)

```text
specs/001-httpfs-qa-infrastructure/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── extensions-manifest.schema.json
│   ├── adapter-lifecycle.md
│   └── ci-workflow.md
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
.github/
└── workflows/
    └── extension-qa.yml

config/
├── extensions.yml
└── schema/
    └── extensions.schema.json

scripts/
└── qa/
    ├── build_duckdb.sh
    ├── validate_manifest.py
    ├── render_matrix.py
    ├── generate_test_config.py
    ├── install_extensions.py
    ├── discover_tests.py
    ├── run_test_group.sh
    ├── normalize_results.py
    └── adapters/
        ├── adapter.sh
        └── httpfs/
            ├── setup.sh
            ├── readiness.sh
            ├── environment.sh
            └── teardown.sh

tests/
├── unit/
│   ├── test_manifest.py
│   ├── test_matrix.py
│   ├── test_test_config.py
│   └── test_results.py
├── contract/
│   ├── test_artifact_layout.py
│   ├── test_no_extension_build.py
│   ├── test_workflow_triggers.py
│   └── test_adapter_contract.py
└── integration/
    └── httpfs/
        └── README.md
```

**Structure Decision**: Use a repository-level CI harness structure rather than an application `src/` tree. Python modules handle deterministic configuration and reporting; shell scripts handle process, container, and toolchain orchestration; adapter directories isolate extension-specific infrastructure from the generic build and test-group contracts.

## Phase 0: Research Output

Research decisions are recorded in [research.md](./research.md). The key resolved questions are:

- standard DuckDB build versus extension-template build;
- artifact portability between the build container and Ubuntu test jobs;
- manifest-generated GitHub Actions matrices;
- isolated prebuilt extension installation and repeated loading in `unittest`;
- HTTPFS service topology and fixture generation;
- safe reuse boundaries for upstream HTTPFS scripts;
- test selection and skip evidence;
- any-branch workflow triggers.

## Phase 1: Design Output

- [data-model.md](./data-model.md) defines DuckDB targets, extension entries, test groups, adapters, artifacts, and evidence.
- [contracts/extensions-manifest.schema.json](./contracts/extensions-manifest.schema.json) defines the manifest's machine-readable contract.
- [contracts/adapter-lifecycle.md](./contracts/adapter-lifecycle.md) defines setup, readiness, environment, evidence, and teardown behavior.
- [contracts/ci-workflow.md](./contracts/ci-workflow.md) defines jobs, dependencies, artifacts, triggers, and failure semantics.
- [quickstart.md](./quickstart.md) explains how maintainers will invoke and inspect the feature after implementation.

## Implementation Sequence

1. Add schema validation and normalize `config/extensions.yml` to the new contract.
2. Add unit and contract tests for manifest validation and arbitrary-branch workflow triggers.
3. Implement matrix and test-config generation.
4. Implement the DuckDB-only build script and relocatable artifact contract.
5. Implement the generic test-group runner with isolated extension installation/loading.
6. Implement the HTTPFS adapter and readiness/teardown behavior.
7. Add the branch-agnostic GitHub Actions workflow.
8. Run the workflow on the feature branch, diagnose failures, and preserve evidence.
9. Confirm no local HTTPFS binary was created and at least one pinned upstream HTTPFS test executed.
10. Run the full selected standard profile and document explicit exclusions.

## Complexity Tracking

No Constitution violations require justification.
