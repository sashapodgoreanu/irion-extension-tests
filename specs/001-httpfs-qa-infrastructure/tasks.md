# Tasks: HTTPFS and DuckLake CI POC

**Goal**: one DuckDB build, two parallel upstream test jobs, both extensions always loaded.

The first version deliberately does not test the QA platform itself. Tasks focus only on producing and running the real compatibility workflow.

## Phase 1 — Restore the POC build

- [x] T001 Add the minimal local extension in `src/qa_test_extension.cpp` and `src/include/qa_test_extension.hpp`.
- [x] T002 Add `CMakeLists.txt`, `extension_config.cmake`, and `Makefile` using the DuckDB extension-template build.
- [x] T003 Pin the DuckDB and extension-ci-tools submodules to `v1.5.4` during CI.
- [x] T004 Add `scripts/build.sh` to build `qa_test`, DuckDB CLI, and `unittest` once.
- [x] T005 Package the release build as one GitHub Actions artifact.

**Checkpoint**: the build job produces one reusable DuckDB runtime. HTTPFS and DuckLake are not compiled.

## Phase 2 — Common runtime for every battery

- [x] T006 Replace the FTS inventory in `config/extensions.yml` with HTTPFS and DuckLake pinned to the revisions declared by DuckDB `v1.5.4`.
- [x] T007 Add `scripts/init-extensions.sql` and use it as the DuckDB `unittest` `init_script` for shared `INSTALL/LOAD` initialization.
- [x] T008 Use a clean HOME in every job and print `duckdb_extensions()` before tests.
- [x] T009 Fail immediately if a required extension cannot be installed or loaded, or if SQLLogicTest still skips it through `require`.
- [x] T010 Run upstream SQLLogicTests through `unittest --test-dir` without copying them.

**Checkpoint**: every test database and additional connection loads HTTPFS and DuckLake together.

## Phase 3 — HTTPFS and DuckLake jobs

- [x] T011 Reuse the HTTPFS repository scripts for Python HTTP, Squid, fixture generation, and MinIO/S3 setup.
- [x] T012 Configure the HTTPFS job to run the complete `test/*` folder from `duckdb-httpfs@c3f215ab360f04dc3d3d5305fa81849c0121f111`.
- [x] T013 Configure the DuckLake job to run the complete `test/*` folder from `ducklake@d318a545571d7d46eb751fa2aa5f6f4389285d3c`.
- [x] T014 Add a two-entry GitHub Actions matrix so HTTPFS and DuckLake run in parallel after the build.
- [x] T015 Ensure HTTPFS service processes and MinIO containers are stopped through a shell trap.

**Checkpoint**: the two complete upstream test folders run independently from the same build artifact.

## Phase 4 — GitHub Actions

- [x] T016 Create `.github/workflows/extension-qa.yml` with unfiltered `push`, `pull_request`, and `workflow_dispatch`.
- [x] T017 Upload build and test logs using normal GitHub Actions artifacts.
- [x] T018 Run the workflow from this feature branch and fix concrete build or test failures.
- [x] T019 Confirm the logs show both `httpfs` and `ducklake` loaded in both jobs.
- [x] T020 Update `README.md` with the small build-once/fan-out flow, shared init script, and complete upstream test folders.

## Done criteria

- exactly one build job;
- exactly two parallel test jobs;
- `qa_test` is the only extension compiled locally;
- HTTPFS and DuckLake are installed and loaded in every test database;
- extension-related `require` directives do not skip the selected suites;
- complete HTTPFS and DuckLake test folders are executed from their pinned upstream repositories;
- HTTPFS infrastructure is prepared by the pinned upstream scripts;
- no branch filter and no generalized QA framework.
