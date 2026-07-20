# Tasks: HTTPFS QA Infrastructure

**Input**: Design documents from `/specs/001-httpfs-qa-infrastructure/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Tests are mandatory for this feature because the specification explicitly requires contract, unit, and integration verification of the CI infrastructure.

**Organization**: Tasks are grouped by user story so each story can be implemented and tested as an independent increment. The repository MUST compile only DuckDB CLI and `unittest`; no task may add HTTPFS or another tested extension to the DuckDB build graph.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it changes different files and has no unfinished dependency.
- **[Story]**: Maps the task to a user story from `spec.md`.
- Every task includes an exact repository path.
- Tests MUST be written first and observed failing before the corresponding implementation task begins.

---

## Phase 1: Setup — Shared Project Structure

**Purpose**: Establish the repository-level QA harness structure and pinned Python tooling without implementing feature behavior.

- [ ] T001 Create Python package markers in `scripts/__init__.py`, `scripts/qa/__init__.py`, and `scripts/qa/adapters/__init__.py`
- [ ] T002 Create test package markers in `tests/__init__.py`, `tests/unit/__init__.py`, `tests/contract/__init__.py`, and `tests/integration/__init__.py`
- [ ] T003 [P] Add pinned QA Python dependencies for YAML and JSON Schema validation in `requirements-qa.txt`
- [ ] T004 [P] Add shared test fixtures and temporary-directory helpers in `tests/helpers.py`
- [ ] T005 [P] Copy the approved manifest contract from `specs/001-httpfs-qa-infrastructure/contracts/extensions-manifest.schema.json` to the runtime path `config/schema/extensions.schema.json`
- [ ] T006 [P] Add generated QA output, isolated runtime directories, service state, and local evidence paths to `.gitignore`
- [ ] T007 Add a repository-level QA command overview and local prerequisites to `docs/qa-development.md`

**Checkpoint**: The source and test directory structure exists, dependencies are pinned, and the runtime schema is present.

---

## Phase 2: Foundational — Blocking Contracts and Generic Models

**Purpose**: Implement the manifest, matrix, runtime configuration, evidence, and adapter contracts that every user story depends on.

**⚠️ CRITICAL**: No user-story implementation may begin until this phase is complete.

### Foundational tests — write and observe failures first

- [ ] T008 [P] Add manifest-schema acceptance and rejection tests in `tests/unit/test_manifest.py`
- [ ] T009 [P] Add immutable commit SHA, unique extension name, unique group ID, and allowed build-target tests in `tests/unit/test_manifest.py`
- [ ] T010 [P] Add build-matrix and test-group-matrix rendering tests in `tests/unit/test_matrix.py`
- [ ] T011 [P] Add all-enabled-extensions install/load ordering tests in `tests/unit/test_test_config.py`
- [ ] T012 [P] Add result classification and machine-readable evidence tests in `tests/unit/test_results.py`
- [ ] T013 [P] Add adapter lifecycle, environment-file, evidence-directory, and unconditional teardown contract tests in `tests/contract/test_adapter_contract.py`

### Foundational implementation

- [ ] T014 Implement typed manifest entities, validation errors, and normalized serialization in `scripts/qa/manifest.py`
- [ ] T015 Implement the manifest CLI with schema validation and normalized JSON output in `scripts/qa/validate_manifest.py`
- [ ] T016 Implement deterministic build and test-group matrix generation in `scripts/qa/render_matrix.py`
- [ ] T017 Implement all-enabled-extension SQL and DuckDB `unittest` configuration generation in `scripts/qa/generate_test_config.py`
- [ ] T018 Implement result states, phase classifications, counts, timestamps, and evidence serialization in `scripts/qa/results.py`
- [ ] T019 Implement human-readable summary generation and normalized `result.json` output in `scripts/qa/normalize_results.py`
- [ ] T020 Implement the generic adapter dispatcher and lifecycle validation in `scripts/qa/adapters/adapter.sh`
- [ ] T021 Update `config/extensions.yml` to satisfy `config/schema/extensions.schema.json`, declare DuckDB `v1.5.4`, enable HTTPFS, and pin `duckdb-httpfs` commit `c3f215ab360f04dc3d3d5305fa81849c0121f111`
- [ ] T022 Add a configuration validation command that runs all foundational unit and contract tests to `scripts/qa/check_configuration.sh`
- [ ] T023 Run `tests/unit/test_manifest.py`, `tests/unit/test_matrix.py`, `tests/unit/test_test_config.py`, `tests/unit/test_results.py`, and `tests/contract/test_adapter_contract.py` and record the passing command in `docs/qa-development.md`

**Checkpoint**: The manifest is the single source of truth; matrices, load configuration, adapter lifecycle, and evidence formats are deterministic and tested.

---

## Phase 3: User Story 1 — Validate a DuckDB Upgrade with HTTPFS (Priority: P1) 🎯 MVP

**Goal**: Build DuckDB CLI and `unittest` exactly once, reuse the artifact, install/load the official HTTPFS binary, and execute at least one pinned upstream HTTPFS SQLLogicTest without compiling HTTPFS.

**Independent Test**: Run the build and one HTTPFS group locally or in CI; confirm the artifact contains `duckdb` and `unittest`, contains zero `.duckdb_extension` files, `INSTALL httpfs; LOAD httpfs;` succeeds in an isolated HOME, and at least one test from the pinned checkout executes through `--test-dir`.

### Tests for User Story 1 — write and observe failures first

- [ ] T024 [P] [US1] Add DuckDB artifact layout, checksum, executable, and relocation contract tests in `tests/contract/test_artifact_layout.py`
- [ ] T025 [P] [US1] Add tests rejecting HTTPFS source paths, extension CMake configs, extension build targets, and locally produced `.duckdb_extension` files in `tests/contract/test_no_extension_build.py`
- [ ] T026 [P] [US1] Add extension installation-source and loaded-state parsing tests in `tests/unit/test_install_extensions.py`
- [ ] T027 [P] [US1] Add upstream include/exclude discovery and empty-inventory tests in `tests/unit/test_discover_tests.py`
- [ ] T028 [P] [US1] Document the initial no-service HTTPFS smoke subset and expected evidence in `tests/integration/httpfs/README.md`

### Implementation for User Story 1

- [ ] T029 [US1] Implement DuckDB checkout, official `linux_amd64` CI-container creation, CMake configuration, and `duckdb`/`unittest` target build in `scripts/qa/build_duckdb.sh`
- [ ] T030 [US1] Add explicit build-tree scans that fail on tested-extension object files, extension targets, or `.duckdb_extension` outputs in `scripts/qa/build_duckdb.sh`
- [ ] T031 [US1] Package `bin/duckdb`, `bin/unittest`, required runtime libraries, `metadata/build.json`, and `checksums/SHA256SUMS` in `scripts/qa/package_duckdb_artifact.sh`
- [ ] T032 [US1] Add clean-directory extraction, checksum verification, `duckdb --version`, `unittest --list-tests`, and relocation smoke tests in `scripts/qa/verify_duckdb_artifact.sh`
- [ ] T033 [US1] Implement isolated HOME/extension/secret/temp/database/report directory creation in `scripts/qa/create_runtime.sh`
- [ ] T034 [US1] Implement prebuilt extension installation, explicit loading, and `duckdb_extensions()` evidence collection in `scripts/qa/install_extensions.py`
- [ ] T035 [US1] Implement upstream test discovery, include/exclude filtering, exclusion-reason evidence, and empty-selection failure in `scripts/qa/discover_tests.py`
- [ ] T036 [US1] Implement the generic test-group runner phases and exit classification in `scripts/qa/run_test_group.sh`
- [ ] T037 [US1] Add the initial HTTPFS smoke profile to `config/extensions.yml` using `adapter: none` and tests that do not require Squid or S3 services
- [ ] T038 [US1] Generate the per-group DuckDB test config with `INSTALL httpfs; LOAD httpfs;` on initialization through `scripts/qa/generate_test_config.py`
- [ ] T039 [US1] Execute the pinned HTTPFS smoke subset with the shared `unittest` binary and `--test-dir` through `scripts/qa/run_test_group.sh`
- [ ] T040 [US1] Publish build metadata, extension inventory, discovered/selected test inventories, test output, and normalized result evidence from `scripts/qa/run_test_group.sh`
- [ ] T041 [US1] Run the User Story 1 contract/unit tests and the HTTPFS smoke integration flow, then document the verified command and evidence layout in `tests/integration/httpfs/README.md`

**Checkpoint**: The MVP proves that this repository compiles only DuckDB and can test an official prebuilt HTTPFS binary against tests from its original repository.

---

## Phase 4: User Story 2 — Run the Same CI from Any Branch (Priority: P1)

**Goal**: Provide one GitHub Actions workflow that validates configuration, builds DuckDB once, and runs generated test groups for pushes, pull requests, and manual dispatch without branch-name filters.

**Independent Test**: Push the workflow from a branch with an arbitrary name and verify that the run is eligible, contains one DuckDB build job for the Linux/Release target, and runs the HTTPFS group using the shared artifact.

### Tests for User Story 2 — write and observe failures first

- [ ] T042 [P] [US2] Add YAML contract tests requiring `push`, `pull_request`, and `workflow_dispatch` and rejecting `branches`/`branches-ignore` in `tests/contract/test_workflow_triggers.py`
- [ ] T043 [P] [US2] Add tests rejecting literal branch comparisons, branch-specific script arguments, and branch-derived artifact names in `tests/contract/test_workflow_triggers.py`
- [ ] T044 [P] [US2] Add job dependency, shared-artifact reuse, matrix generation, and `if: always()` evidence-upload tests in `tests/contract/test_workflow_structure.py`
- [ ] T045 [P] [US2] Add immutable GitHub Action SHA pinning tests in `tests/contract/test_workflow_structure.py`

### Implementation for User Story 2

- [ ] T046 [US2] Create `.github/workflows/extension-qa.yml` with unfiltered `push`, `pull_request`, and `workflow_dispatch` triggers
- [ ] T047 [US2] Add a `validate-manifest` job that installs pinned QA dependencies, validates `config/extensions.yml`, and publishes normalized build/test matrices in `.github/workflows/extension-qa.yml`
- [ ] T048 [US2] Add a `build-duckdb` matrix job that invokes `scripts/qa/build_duckdb.sh`, packages the shared artifact, verifies relocation, and uploads it in `.github/workflows/extension-qa.yml`
- [ ] T049 [US2] Add a generated `test-group` matrix job that downloads the matching DuckDB artifact and invokes `scripts/qa/run_test_group.sh` in `.github/workflows/extension-qa.yml`
- [ ] T050 [US2] Add dynamic concurrency based on workflow/event/ref identifiers without literal branch names in `.github/workflows/extension-qa.yml`
- [ ] T051 [US2] Pin checkout, setup, cache, artifact, and other reusable Actions to immutable commit SHAs in `.github/workflows/extension-qa.yml`
- [ ] T052 [US2] Add unconditional job-summary and evidence-artifact publication for validation, build, and test-group failures in `.github/workflows/extension-qa.yml`
- [ ] T053 [US2] Add workflow contract tests to `scripts/qa/check_configuration.sh`
- [ ] T054 [US2] Push the feature branch, verify that GitHub Actions creates a run without a branch filter, and record the run evidence requirements in `tests/integration/httpfs/README.md`

**Checkpoint**: The same CI definition is eligible from any branch and reuses one DuckDB artifact across generated test jobs.

---

## Phase 5: User Story 3 — Provision HTTPFS Test Services Reproducibly (Priority: P2)

**Goal**: Add a dedicated HTTPFS adapter that provisions the local HTTP server, Squid proxy, and MinIO/S3-compatible test service while keeping infrastructure out of the DuckDB build job.

**Independent Test**: Run the adapter lifecycle, prove every readiness check passes, execute the selected service-backed HTTPFS tests, and verify teardown plus service-log retention after both success and forced failure.

### Tests for User Story 3 — write and observe failures first

- [ ] T055 [P] [US3] Add HTTP server, Squid, and MinIO command-generation tests in `tests/unit/test_httpfs_adapter.py`
- [ ] T056 [P] [US3] Add readiness timeout, unhealthy-service classification, and port-conflict tests in `tests/unit/test_httpfs_adapter.py`
- [ ] T057 [P] [US3] Add forbidden-command tests rejecting `make`, CMake, Ninja, and HTTPFS build targets in `tests/contract/test_httpfs_adapter_safety.py`
- [ ] T058 [P] [US3] Add teardown-on-success, teardown-on-failure, and service-log preservation tests in `tests/contract/test_httpfs_adapter_safety.py`
- [ ] T059 [P] [US3] Define the service-backed HTTPFS standard-profile expectations and explicit exclusions in `tests/integration/httpfs/README.md`

### Implementation for User Story 3

- [ ] T060 [P] [US3] Implement local Python HTTP server startup, allocated-port handling, fixture root, PID tracking, and logs in `scripts/qa/adapters/httpfs/setup_http_server.sh`
- [ ] T061 [P] [US3] Implement pinned Squid installation/configuration, startup, PID tracking, and logs in `scripts/qa/adapters/httpfs/setup_squid.sh`
- [ ] T062 [P] [US3] Implement pinned MinIO/S3-compatible Compose startup, isolated project naming, volumes, host aliases, and logs in `scripts/qa/adapters/httpfs/setup_minio.sh`
- [ ] T063 [US3] Implement the adapter orchestration entry point and forbidden-command guard in `scripts/qa/adapters/httpfs/setup.sh`
- [ ] T064 [P] [US3] Implement HTTP server readiness checks and timeout evidence in `scripts/qa/adapters/httpfs/readiness_http_server.sh`
- [ ] T065 [P] [US3] Implement Squid readiness checks and timeout evidence in `scripts/qa/adapters/httpfs/readiness_squid.sh`
- [ ] T066 [P] [US3] Implement MinIO health, bucket/fixture readiness, and timeout evidence in `scripts/qa/adapters/httpfs/readiness_minio.sh`
- [ ] T067 [US3] Implement aggregate readiness classification in `scripts/qa/adapters/httpfs/readiness.sh`
- [ ] T068 [US3] Implement fixture and presigned-URL generation using only the shared DuckDB CLI and declared prebuilt setup tools in `scripts/qa/adapters/httpfs/generate_fixtures.sh`
- [ ] T069 [US3] Implement redacted environment-file generation for HTTPFS upstream variables in `scripts/qa/adapters/httpfs/environment.sh`
- [ ] T070 [US3] Implement unconditional process/container teardown, orphan detection, and cleanup evidence in `scripts/qa/adapters/httpfs/teardown.sh`
- [ ] T071 [US3] Add the HTTPFS standard service-backed group, include/exclude rules, timeout, exclusion reasons, and `adapter: httpfs` to `config/extensions.yml`
- [ ] T072 [US3] Integrate adapter setup, readiness, environment import, evidence, and unconditional teardown into `scripts/qa/run_test_group.sh`
- [ ] T073 [US3] Extend `.github/workflows/extension-qa.yml` permissions and runner setup only as needed for Squid and Docker Compose, without moving service setup into `build-duckdb`
- [ ] T074 [US3] Execute the service-backed HTTPFS profile in CI, classify any infrastructure failures separately, and document retained evidence in `tests/integration/httpfs/README.md`

**Checkpoint**: HTTPFS service-backed tests run reproducibly through an isolated adapter, while the DuckDB build remains unchanged and extension-free.

---

## Phase 6: User Story 4 — Reuse the Infrastructure for Future Extensions (Priority: P3)

**Goal**: Demonstrate that a new extension or adapter can be added through manifest/configuration contracts without rewriting the DuckDB build implementation or coupling generic code to HTTPFS.

**Independent Test**: Add a disabled synthetic extension/group fixture in tests, render the matrices, and verify it uses the existing DuckDB artifact and either `adapter: none` or its own adapter contract without changing `build_duckdb.sh`.

### Tests for User Story 4 — write and observe failures first

- [ ] T075 [P] [US4] Add multi-extension all-loaded-set and deterministic load-order tests in `tests/unit/test_matrix.py` and `tests/unit/test_test_config.py`
- [ ] T076 [P] [US4] Add synthetic `adapter: none` and service-backed adapter registry tests in `tests/contract/test_adapter_contract.py`
- [ ] T077 [P] [US4] Add a regression test proving manifest expansion does not alter `scripts/qa/build_duckdb.sh` inputs or targets in `tests/contract/test_no_extension_build.py`
- [ ] T078 [P] [US4] Add isolated writable-directory and unique service-namespace tests for parallel groups in `tests/contract/test_parallel_isolation.py`

### Implementation for User Story 4

- [ ] T079 [US4] Implement adapter-name lookup, `none` adapter behavior, unknown-adapter failure, and extension-independent dispatch in `scripts/qa/adapters/adapter.sh`
- [ ] T080 [US4] Extend matrix generation to emit multiple groups and preserve one shared build artifact reference per DuckDB target in `scripts/qa/render_matrix.py`
- [ ] T081 [US4] Extend test-config generation to install/load the complete enabled extension set for every owner group in `scripts/qa/generate_test_config.py`
- [ ] T082 [US4] Add per-group runtime IDs, directories, Docker Compose project names, ports, and evidence namespaces in `scripts/qa/create_runtime.sh`
- [ ] T083 [US4] Add disabled example entries for a no-service extension and a PostgreSQL-backed extension to `config/extensions.examples.yml`
- [ ] T084 [US4] Document the exact steps for adding an extension, pinning its test commit, selecting an adapter, and preserving the DuckDB-only build rule in `docs/adding-an-extension.md`
- [ ] T085 [US4] Run the multi-extension synthetic contract suite and record the passing commands in `docs/adding-an-extension.md`

**Checkpoint**: New extensions and adapters can be introduced declaratively without modifying the shared DuckDB build implementation.

---

## Phase 7: Polish and Cross-Cutting Quality Gates

**Purpose**: Validate the complete feature against the Constitution, specification, contracts, evidence requirements, and maintainer quickstart.

- [ ] T086 [P] Add malformed manifest, missing binary, failed load, empty discovery, timeout, crash, and cleanup-failure regression cases across `tests/unit/` and `tests/contract/`
- [ ] T087 [P] Add secret-redaction tests for environment files, logs, summaries, and `result.json` in `tests/contract/test_secret_redaction.py`
- [ ] T088 [P] Add deterministic manifest digest, source SHA, action SHA, image digest, and package-version evidence checks in `tests/contract/test_reproducibility.py`
- [ ] T089 Add a single local quality-gate script running unit tests, contract tests, schema validation, workflow validation, and shell syntax checks in `scripts/qa/quality_gate.sh`
- [ ] T090 Add shell static checks for all files under `scripts/qa/**/*.sh` and Python compilation/import checks for `scripts/qa/**/*.py` to `scripts/qa/quality_gate.sh`
- [ ] T091 Update `README.md` with the implemented build-once/fan-out workflow, HTTPFS example, artifact flow, and arbitrary-branch invocation
- [ ] T092 Update `docs/ci-architecture.md` with actual job names, artifact contract, adapter lifecycle, isolation boundaries, and failure classifications
- [ ] T093 Execute every command in `specs/001-httpfs-qa-infrastructure/quickstart.md`, correct any divergence, and update the document with verified output expectations
- [ ] T094 Run `.github/workflows/extension-qa.yml` from a non-default arbitrarily named branch and verify zero literal branch filters through `tests/contract/test_workflow_triggers.py`
- [ ] T095 Verify the successful CI evidence proves exactly one DuckDB build, zero locally built `.duckdb_extension` files, successful official HTTPFS install/load, non-empty upstream discovery, and at least one completed HTTPFS test
- [ ] T096 Re-run the same commit with caches disabled and compare manifest digest, pinned source SHAs, test inventory, and result classification; document the comparison in `tests/integration/httpfs/README.md`
- [ ] T097 Complete a final Constitution Check against `.specify/memory/constitution.md` and record the result in `specs/001-httpfs-qa-infrastructure/checklists/implementation.md`

---

## Dependencies and Execution Order

### Phase dependencies

- **Phase 1 — Setup**: No dependencies; starts immediately.
- **Phase 2 — Foundational**: Depends on Phase 1 and blocks every user story.
- **Phase 3 — US1 MVP**: Depends on Phase 2.
- **Phase 4 — US2 Any-branch CI**: Depends on the executable US1 scripts and artifact contract from Phase 3.
- **Phase 5 — US3 HTTPFS services**: Depends on the generic runner from Phase 3; it can be developed in parallel with the final parts of Phase 4 once the runner contract is stable.
- **Phase 6 — US4 Extensibility**: Depends on the manifest/matrix foundation and generic runner; final verification depends on Phases 4 and 5.
- **Phase 7 — Polish**: Depends on all selected user stories being complete.

### User-story dependencies

```text
Setup
  └── Foundational
        └── US1: DuckDB + official HTTPFS smoke MVP
              ├── US2: arbitrary-branch GitHub Actions
              └── US3: HTTPFS service adapter
                    └── US4: reusable multi-extension infrastructure
                          └── Polish and full quality gates
```

- **US1** is the minimum deployable proof and has no dependency on another user story.
- **US2** wraps the US1 commands in branch-agnostic CI and must not duplicate their behavior in YAML.
- **US3** extends the US1 group through an adapter; it must not modify the DuckDB build.
- **US4** generalizes the contracts after the real HTTPFS adapter proves them.

### Within each user story

1. Write the listed unit/contract tests.
2. Run them and confirm they fail for the expected missing behavior.
3. Implement the smallest behavior that satisfies the tests.
4. Run the story's independent integration test.
5. Inspect and retain evidence.
6. Commit each completed logical group before moving to the next group.

---

## Parallel Opportunities

### Setup and foundational

- T003–T006 can run in parallel.
- T008–T013 can run in parallel before T014–T020.
- T014, T016, T017, T018, and T020 affect different modules and can be implemented in parallel after their tests exist.

### User Story 1

- T024–T028 can run in parallel.
- T031, T033, T034, and T035 can run in parallel after the artifact/manifest contracts are stable.
- T036 depends on T033–T035; T039 depends on T036–T038.

### User Story 2

- T042–T045 can run in parallel.
- T047, T048, and T049 are separate jobs but share `.github/workflows/extension-qa.yml`; coordinate or implement sequentially to avoid file conflicts.

### User Story 3

- T055–T059 can run in parallel.
- T060–T062 can run in parallel.
- T064–T066 can run in parallel after their corresponding setup scripts.
- T068, T069, and T070 affect different files and can run in parallel after the service contracts are fixed.

### User Story 4

- T075–T078 can run in parallel.
- T079–T083 affect separate files/modules and can largely run in parallel after tests exist.

---

## Parallel Example: HTTPFS Adapter

```text
Task T060: Implement Python HTTP server setup in scripts/qa/adapters/httpfs/setup_http_server.sh
Task T061: Implement Squid setup in scripts/qa/adapters/httpfs/setup_squid.sh
Task T062: Implement MinIO setup in scripts/qa/adapters/httpfs/setup_minio.sh

Then:

Task T064: Implement HTTP server readiness in scripts/qa/adapters/httpfs/readiness_http_server.sh
Task T065: Implement Squid readiness in scripts/qa/adapters/httpfs/readiness_squid.sh
Task T066: Implement MinIO readiness in scripts/qa/adapters/httpfs/readiness_minio.sh
```

These tasks are parallel because they operate on independent service-specific files. T063 and T067 integrate them only after the individual scripts exist.

---

## Implementation Strategy

### MVP first

1. Complete Phase 1.
2. Complete Phase 2.
3. Complete Phase 3 — US1.
4. Stop and validate:
   - only DuckDB CLI and `unittest` were built;
   - no local HTTPFS binary exists;
   - official HTTPFS installs and loads;
   - at least one pinned upstream test executes.
5. Commit the validated MVP before adding GitHub Actions or service-backed tests.

### Incremental delivery

1. **Foundation**: validated manifest, deterministic matrix, load config, evidence contracts.
2. **US1 MVP**: DuckDB-only build plus official HTTPFS smoke test.
3. **US2**: arbitrary-branch CI using the same scripts and artifact.
4. **US3**: HTTPFS service adapter and broader upstream profile.
5. **US4**: demonstrate extension/adapter reuse without build changes.
6. **Polish**: full failure-mode, reproducibility, documentation, and Constitution validation.

### Suggested commit boundaries

- Setup and runtime schema.
- Manifest/matrix/test-config foundation with tests.
- DuckDB-only build artifact with contract tests.
- Generic isolated install/load/test runner.
- HTTPFS smoke profile.
- Branch-agnostic GitHub Actions workflow.
- HTTPFS service adapter.
- Multi-extension generalization.
- Documentation and final quality gates.

---

## Notes

- `[P]` means different files and no unfinished dependency; it does not override semantic dependencies listed above.
- `[US1]`–`[US4]` provide traceability to the specification user stories.
- No task authorizes compiling HTTPFS or any tested extension.
- The build may contain DuckDB's own mandatory standard components, but the repository must not add external tested extensions to CMake.
- Safe upstream HTTPFS scripts may be wrapped only after review; commands invoking `make`, CMake, Ninja, or extension build targets are forbidden.
- All GitHub Actions must be pinned to immutable commit SHAs before the workflow can pass its contract tests.
- Every workflow trigger and condition must remain branch-name agnostic.
- Every logical implementation group must be committed before proceeding, as required by the repository workflow.
