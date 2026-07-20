# Research: HTTPFS QA Infrastructure

**Feature**: `001-httpfs-qa-infrastructure`  
**Date**: 2026-07-20

## Decision 1: Build the standard DuckDB distribution, not an extension-template project

**Decision**: Check out DuckDB `v1.5.4` directly and build the `duckdb` and `unittest` targets. Do not provide an Irion `DUCKDB_EXTENSION_CONFIGS` file, external extension source directory, `TEST_WITH_LOADABLE_EXTENSION`, or extension build target.

**Rationale**: This repository validates prebuilt extensions against a selected DuckDB runtime. Adding the extension under test to CMake would test source compatibility and local linkage rather than the runtime composition used by Irion.

DuckDB's upstream base configuration includes `core_functions` and `parquet` as essential standard-distribution components. They are accepted as DuckDB build internals; no external/tested extension source is added by this repository.

**Alternatives rejected**:

- Building HTTPFS as `httpfs_loadable_extension`: rejected because it violates the repository Constitution and can test a different revision from the official binary.
- Linking HTTPFS statically into `unittest`: rejected because it does not exercise `INSTALL`/`LOAD` behavior.
- Reusing the DuckDB extension template Makefile: rejected because it is designed to build a product extension.

## Decision 2: Use the official DuckDB Linux toolchain container only for the build job

**Decision**: Build DuckDB inside the `linux_amd64` container derived from pinned `extension-ci-tools v1.5.4`, then package the DuckDB CLI and `unittest` into a relocatable artifact.

**Rationale**: This matches the toolchain family used by DuckDB extension distribution while keeping service-heavy HTTPFS testing outside the build container. The produced Linux binaries should run on the newer GitHub-hosted Ubuntu environment, subject to an explicit relocation and `ldd` smoke test.

**Alternatives rejected**:

- Running every job inside the build container: rejected because the HTTPFS adapter needs Docker Compose, host aliases, Squid, background services, and accessible service logs.
- Building directly on `ubuntu-24.04`: rejected for the first implementation because it would diverge from the pinned DuckDB CI toolchain.
- Publishing a Docker image containing the build: rejected as unnecessary for the initial Linux-only scope and harder to inspect as a simple workflow artifact.

## Decision 3: Separate manifest validation, DuckDB build, and test-group execution

**Decision**: Use three logical workflow stages:

1. validate manifest and render matrix;
2. build DuckDB once;
3. execute test groups from the generated matrix in parallel.

**Rationale**: This enforces the build-once contract and makes adding an extension a data/configuration change rather than a copy-pasted CI job. It also allows configuration errors to fail before expensive compilation.

**Alternatives rejected**:

- One monolithic job: rejected because every future extension would serialize behind unrelated services and make evidence harder to classify.
- One full build per extension: rejected because it wastes time and can hide differences between supposedly identical DuckDB runtimes.
- Hand-written job per extension: rejected because manifest and workflow would drift.

## Decision 4: Install prebuilt extensions in an isolated HOME, then load them in each test database instance

**Decision**: Each test-group job creates a fresh HOME and extension directory, performs explicit `INSTALL` statements for every enabled extension, performs a preflight `LOAD`, and verifies `duckdb_extensions()`. A generated DuckDB test config emits the enabled `LOAD` statements during `unittest` database initialization.

**Rationale**: Installing once per job avoids repeated network downloads while ensuring every SQLLogicTest database instance loads the complete enabled extension set. The isolated HOME proves that a runner-global installation did not satisfy the test accidentally.

**Alternatives rejected**:

- Enabling automatic install/load: rejected because implicit behavior can hide a missing manifest entry or load-order issue.
- Loading only HTTPFS for HTTPFS-owned tests: rejected because the repository exists to detect cross-extension conflicts.
- Installing into the runner's default HOME: rejected because state can leak between commands and caches.

## Decision 5: Treat the extension manifest as the only matrix source

**Decision**: A Python command validates `config/extensions.yml` against a committed JSON Schema and emits normalized JSON containing DuckDB target metadata, all enabled extension runtime statements, and one matrix entry per test group.

**Rationale**: GitHub Actions expressions are not a suitable validation or transformation language. A normalized intermediate document keeps workflow YAML small and makes generation testable locally.

**Alternatives rejected**:

- Parsing YAML independently in each job: rejected because normalization and validation behavior could diverge.
- Duplicating HTTPFS repository/commit/filter values in workflow YAML: rejected because the manifest would stop being the source of truth.
- Generating workflow files and committing them: rejected for the first version because dynamic matrices already satisfy the need.

## Decision 6: Use a formal adapter lifecycle for HTTPFS infrastructure

**Decision**: Implement HTTPFS behind five generic phases:

1. configuration validation;
2. setup;
3. readiness;
4. environment export;
5. unconditional teardown and evidence collection.

The adapter provisions a Python HTTP server, Squid proxy, and S3-compatible MinIO service. Each service has an independent readiness probe and log path.

**Rationale**: HTTPFS is the first proof of a pattern that must later support PostgreSQL, SQL Server, catalogs, object stores, and other infrastructure. A lifecycle contract prevents extension-specific setup from leaking into the generic workflow.

**Alternatives rejected**:

- Inline all service commands in workflow YAML: rejected because the adapter would be impossible to reuse or test locally.
- Use GitHub Actions `services` exclusively: rejected because HTTPFS needs host aliases, fixture generation, proxy configuration, and upstream Compose behavior that are easier to control through an adapter.
- Run the entire upstream integration workflow unchanged: rejected because it invokes `make` and builds HTTPFS.

## Decision 7: Reuse safe upstream HTTPFS scripts selectively

**Decision**: Reuse pinned upstream scripts or Compose definitions only after inspecting them and wrapping them with policy checks. The wrapper must never invoke `make`, CMake, Ninja, or an HTTPFS build target.

The pinned upstream integration workflow demonstrates these required services and variables:

- Python HTTP server on port 8008;
- Squid on port 3128;
- MinIO/S3 test server on port 9000;
- `S3_TEST_SERVER_AVAILABLE=1`;
- AWS test credentials and region;
- `DUCKDB_S3_ENDPOINT=duckdb-minio.com:9000`;
- `DUCKDB_S3_USE_SSL=false`.

**Rationale**: Keeping fixture and service behavior aligned with the pinned suite improves fidelity, but blindly executing upstream CI would violate the no-extension-build rule.

**Alternatives rejected**:

- Copying upstream scripts into this repository: rejected because they would drift.
- Reimplementing every fixture immediately: rejected as unnecessary before the upstream behavior is proven insufficient.
- Trusting arbitrary scripts from a mutable branch: rejected because only pinned commits are allowed.

## Decision 8: Allow adapter-scoped prebuilt setup tools

**Decision**: The HTTPFS adapter may dynamically install prebuilt setup-only extensions such as `tpch` when required to generate upstream fixtures. These tools are not part of the enabled Irion compatibility extension set unless separately declared.

**Rationale**: The pinned `generate_presigned_url.sh` uses `CALL DBGEN` and therefore needs TPCH functionality. Installing a prebuilt fixture tool preserves the rule that this repository compiles only DuckDB.

Setup-only tools must be declared in adapter configuration, use isolated extension storage, and appear in evidence separately from enabled runtime extensions.

**Alternatives rejected**:

- Building TPCH locally: rejected by the Constitution.
- Pretending TPCH is an Irion compatibility extension: rejected because it changes the runtime composition being tested.
- Editing upstream fixture SQL without documenting the divergence: rejected because it reduces fidelity.

## Decision 9: Start with a standard non-slow HTTPFS profile and explicit exclusions

**Decision**: Discover the pinned HTTPFS suite from its repository, include standard `.test` files, exclude `.test_slow` initially, and explicitly list any tests that need real cloud credentials, unsupported platforms, or nondeterministic public endpoints.

**Rationale**: The first infrastructure feature must be reliable enough to run on every branch. Slow and credentialed categories can be added later as separate profiles while remaining visible in the inventory.

Every excluded test needs a category, reason, and owner. The report records discovered, selected, excluded, skipped, passed, and failed counts.

**Alternatives rejected**:

- Run one hand-picked smoke test only: rejected because it would not validate the adapter sufficiently.
- Run every slow/cloud test immediately: rejected because it would make branch CI expensive and require secrets outside the initial scope.
- Let upstream `require` statements silently skip everything: rejected because zero meaningful execution must fail.

## Decision 10: Use unfiltered generic workflow triggers

**Decision**: The workflow uses `push`, `pull_request`, and `workflow_dispatch` with no branch filters. Concurrency keys use dynamic workflow/event/ref identifiers and contain no literal repository branch names.

**Rationale**: Feature branches must validate the CI implementation itself. After the workflow exists on the default branch, manual dispatch can select any available ref; before merge, normal branch pushes and pull requests provide feature validation.

**Alternatives rejected**:

- Restricting `push` to `main`: rejected because feature branches would not run.
- Embedding the feature branch name temporarily: rejected because temporary filters are easily left behind.
- Using only `workflow_dispatch`: rejected because manual dispatch visibility depends on the workflow existing on the default branch.

## Decision 11: Pin supply-chain inputs and preserve evidence on failure

**Decision**: Pin DuckDB, CI tools, HTTPFS test source, Python packages, service images, and GitHub Actions to immutable references. Upload build, setup, service, discovery, test, and cleanup evidence with `if: always()`.

**Rationale**: Compatibility results must be attributable to exact inputs and useful when infrastructure fails before tests start.

**Alternatives rejected**:

- Mutable action tags such as `@v4`: rejected for the official implementation because the Constitution requires reproducibility.
- Logs only in the Actions console: rejected because retention and diagnosis are weaker and machine-readable comparison is impossible.
- Treat all failures as a generic non-zero exit: rejected because infrastructure and functional regressions require different ownership.
