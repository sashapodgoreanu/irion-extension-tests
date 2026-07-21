# Tasks: HTTPFS, DuckLake, and MSSQL CI POC

**Goal**: one DuckDB build and three parallel upstream test jobs, with the supported extensions installed together.

The first version deliberately does not test the QA platform itself. Tasks focus only on producing and running the real compatibility workflow.

## Phase 1 — Restore the POC build

- [x] T001 Add the minimal local extension in `src/qa_test_extension.cpp` and `src/include/qa_test_extension.hpp`.
- [x] T002 Add `CMakeLists.txt`, `extension_config.cmake`, and `Makefile` using the DuckDB extension-template build.
- [x] T003 Pin the DuckDB and extension-ci-tools submodules to `v1.5.4` during CI.
- [x] T004 Add `scripts/build.sh` to build `qa_test`, DuckDB CLI, and `unittest` once.
- [x] T005 Package the release build as one GitHub Actions artifact.

**Checkpoint**: the build job produces one reusable DuckDB runtime. HTTPFS, DuckLake, and MSSQL are not compiled locally.

## Phase 2 — Common runtime for every battery

- [x] T006 Declare HTTPFS, DuckLake, and the MSSQL community release in `config/extensions.yml`.
- [x] T007 Separate one-time installation (`install-extensions.sql`) from database initialization (`init-extensions.sql`).
- [x] T008 Use a clean HOME in every job and print `duckdb_extensions()` before tests.
- [x] T009 Fail immediately if a required extension cannot be installed or loaded, or if SQLLogicTest still skips it through `require`.
- [x] T010 Run upstream SQLLogicTests through `unittest --test-dir` without copying them.

**Checkpoint**: normal test databases load HTTPFS, DuckLake, and MSSQL together. Lifecycle tests deliberately unload only the extension whose autoload behavior they verify.

## Phase 3 — HTTPFS and DuckLake jobs

- [x] T011 Reuse the HTTPFS repository scripts for Python HTTP, Squid, fixture generation, and MinIO/S3 setup.
- [x] T012 Run HTTPFS `test/sql/*` with the compatibility set loaded and `test/extension/*` with the upstream-compatible autoload lifecycle.
- [x] T013 Configure the DuckLake job to run the complete `test/*` folder from `ducklake@d318a545571d7d46eb751fa2aa5f6f4389285d3c`.
- [x] T014 Add explicit HTTPFS and DuckLake matrix entries that fan out from the shared build.
- [x] T015 Ensure HTTPFS service processes and MinIO containers are stopped through a shell trap.

**Checkpoint**: the complete upstream test folders run independently from the same build artifact without invalidating HTTPFS or DuckLake lifecycle tests.

## Phase 4 — GitHub Actions

- [x] T016 Create `.github/workflows/extension-qa.yml` with unfiltered `push`, `pull_request`, and `workflow_dispatch`.
- [x] T017 Upload build and test logs using normal GitHub Actions artifacts.
- [ ] T018 Run the workflow after the lifecycle splits and fix concrete build or test failures.
- [ ] T019 Confirm the logs show no skips caused by missing `httpfs`, `ducklake`, `mssql`, `json`, `tpch`, `tpcds`, `icu`, `postgres_scanner`, or `sqlite_scanner`.
- [x] T020 Update `README.md` with the build-once/fan-out flow and complete upstream test folders.

## Phase 5 — MSSQL community release battery

- [x] T021 Pin MSSQL to the published `v0.2.1` release tag and require the community binary to report version `0.2.1`.
- [x] T022 Add MSSQL to the shared installation/loading profiles so HTTPFS and DuckLake also exercise coexistence with MSSQL.
- [x] T023 Start SQL Server 2022 from the pinned upstream Compose file and execute the pinned upstream seed SQL files.
- [x] T024 Reuse the pinned upstream integration smoke script and run the complete `test/sql/*` folder with the shared `unittest` binary.
- [x] T025 Add maintainer/AI comments that forbid moving refs and define the coordinated release-update procedure.
- [ ] T026 Confirm the MSSQL job executes real SQLLogicTest cases without mandatory `require-env` skips and passes against SQL Server.

## Done criteria

- exactly one build job;
- exactly three parallel test jobs;
- `qa_test` is the only extension compiled locally;
- HTTPFS, DuckLake, and MSSQL are installed in every test job;
- normal suites load HTTPFS, DuckLake, and MSSQL together;
- HTTPFS and DuckLake autoloading tests preserve their required unloaded starting state;
- extension-related `require` directives do not skip the selected suites;
- complete HTTPFS, DuckLake, and MSSQL test folders are executed from pinned upstream repositories/tags;
- HTTPFS infrastructure is prepared by pinned upstream scripts;
- MSSQL SQL Server and fixture setup is driven by the pinned release assets;
- MSSQL remains pinned to a published release tag and is version-aligned with DuckDB Community;
- no branch filter and no generalized QA framework.
