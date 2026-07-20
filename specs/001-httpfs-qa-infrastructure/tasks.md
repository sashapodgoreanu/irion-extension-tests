# Tasks: HTTPFS and DuckLake CI POC

**Goal**: one DuckDB build, two parallel upstream test jobs, both extensions always loaded.

The first version deliberately does not test the QA platform itself. Tasks focus only on producing and running the real compatibility workflow.

## Phase 1 — Restore the POC build

- [ ] T001 Add the minimal local extension in `src/qa_test_extension.cpp` and `src/include/qa_test_extension.hpp`.
- [ ] T002 Add `CMakeLists.txt`, `extension_config.cmake`, and `Makefile` using the DuckDB extension-template build.
- [ ] T003 Pin the DuckDB and extension-ci-tools submodules to `v1.5.4` during CI.
- [ ] T004 Add `scripts/build.sh` to build `qa_test`, DuckDB CLI, and `unittest` once.
- [ ] T005 Package the release build as one GitHub Actions artifact.

**Checkpoint**: the build job produces one reusable DuckDB runtime. HTTPFS and DuckLake are not compiled.

## Phase 2 — Common runtime for every battery

- [ ] T006 Replace the FTS inventory in `config/extensions.yml` with HTTPFS and DuckLake pinned to the revisions declared by DuckDB `v1.5.4`.
- [ ] T007 Add `scripts/run-tests.sh` with one shared initialization sequence: `INSTALL/LOAD httpfs` and `INSTALL/LOAD ducklake`.
- [ ] T008 Use a clean HOME in every job and print `duckdb_extensions()` before tests.
- [ ] T009 Fail immediately if either extension cannot be installed or loaded.
- [ ] T010 Run upstream SQLLogicTests through `unittest --test-dir` without copying them.

**Checkpoint**: every test battery contains HTTPFS and DuckLake together.

## Phase 3 — HTTPFS and DuckLake jobs

- [ ] T011 Add `scripts/setup-httpfs.sh` using the Python HTTP-server convention from the upstream HTTPFS workflow.
- [ ] T012 Configure the HTTPFS job to run `test/sql/curl_client/test_relative_path_parsing.test` from `duckdb-httpfs@c3f215ab360f04dc3d3d5305fa81849c0121f111`.
- [ ] T013 Configure the DuckLake job to run `test/sql/ducklake_basic.test` from `ducklake@d318a545571d7d46eb751fa2aa5f6f4389285d3c`.
- [ ] T014 Add a two-entry GitHub Actions matrix so HTTPFS and DuckLake run in parallel after the build.
- [ ] T015 Ensure HTTPFS service processes are stopped through a shell trap.

**Checkpoint**: the two real upstream tests run independently from the same build artifact.

## Phase 4 — GitHub Actions

- [ ] T016 Create `.github/workflows/extension-qa.yml` with unfiltered `push`, `pull_request`, and `workflow_dispatch`.
- [ ] T017 Upload build and test logs using normal GitHub Actions artifacts.
- [ ] T018 Run the workflow from this feature branch and fix concrete build or test failures.
- [ ] T019 Confirm the logs show both `httpfs` and `ducklake` loaded in both jobs.
- [ ] T020 Update `README.md` with the small build-once/fan-out flow and the first two test subsets.

## Done criteria

- exactly one build job;
- exactly two parallel test jobs;
- `qa_test` is the only extension compiled locally;
- HTTPFS and DuckLake are both installed and loaded in every test job;
- HTTPFS and DuckLake tests are executed from their pinned upstream repositories;
- no branch filter and no generalized QA framework.
