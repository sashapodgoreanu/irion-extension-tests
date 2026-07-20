# Tasks: HTTPFS and DuckLake CI POC

**Goal**: one DuckDB build and two parallel upstream test jobs, with the supported extensions installed together.

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
- [x] T007 Separate one-time installation (`install-extensions.sql`) from database initialization (`init-extensions.sql`).
- [x] T008 Use a clean HOME in every job and print `duckdb_extensions()` before tests.
- [x] T009 Fail immediately if a required extension cannot be installed or loaded, or if SQLLogicTest still skips it through `require`.
- [x] T010 Run upstream SQLLogicTests through `unittest --test-dir` without copying them.

**Checkpoint**: normal test databases load HTTPFS and DuckLake together. HTTPFS autoloading tests deliberately start with HTTPFS unloaded because that lifecycle is what they verify.

## Phase 3 — HTTPFS and DuckLake jobs

- [x] T011 Reuse the HTTPFS repository scripts for Python HTTP, Squid, fixture generation, and MinIO/S3 setup.
- [x] T012 Run HTTPFS `test/sql/*` with both extensions loaded and `test/extension/*` with the upstream-compatible autoload lifecycle.
- [x] T013 Configure the DuckLake job to run the complete `test/*` folder from `ducklake@d318a545571d7d46eb751fa2aa5f6f4389285d3c`.
- [x] T014 Add a two-entry GitHub Actions matrix so HTTPFS and DuckLake run in parallel after the build.
- [x] T015 Ensure HTTPFS service processes and MinIO containers are stopped through a shell trap.

**Checkpoint**: the complete upstream test folders run independently from the same build artifact without invalidating HTTPFS lifecycle tests.

## Phase 4 — GitHub Actions

- [x] T016 Create `.github/workflows/extension-qa.yml` with unfiltered `push`, `pull_request`, and `workflow_dispatch`.
- [x] T017 Upload build and test logs using normal GitHub Actions artifacts.
- [ ] T018 Run the workflow after the HTTPFS lifecycle split and fix concrete build or test failures.
- [ ] T019 Confirm the logs show no skips caused by missing `httpfs`, `ducklake`, `json`, `tpch`, or `icu`.
- [x] T020 Update `README.md` with the small build-once/fan-out flow and complete upstream test folders.

## Done criteria

- exactly one build job;
- exactly two parallel test jobs;
- `qa_test` is the only extension compiled locally;
- HTTPFS and DuckLake are installed in every test job;
- normal suites load HTTPFS and DuckLake together;
- HTTPFS autoloading tests preserve their required unloaded starting state;
- extension-related `require` directives do not skip the selected suites;
- complete HTTPFS and DuckLake test folders are executed from their pinned upstream repositories;
- HTTPFS infrastructure is prepared by the pinned upstream scripts;
- no branch filter and no generalized QA framework.
