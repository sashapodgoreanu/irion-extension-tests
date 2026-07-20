# Feature Specification: HTTPFS QA Infrastructure

**Feature Branch**: `001-httpfs-qa-infrastructure`

**Created**: 2026-07-20

**Status**: Draft

**Input**: Create the first reusable QA infrastructure for this repository and validate it with the upstream HTTPFS test suite. The workflow must be invokable from any branch and must not contain branch-name filters.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Validate a DuckDB upgrade with HTTPFS (Priority: P1)

As an Irion engineer evaluating a DuckDB version, I can run one CI workflow that builds only DuckDB and its `unittest` executable, installs the official HTTPFS extension dynamically, and executes the original HTTPFS SQLLogicTests from the pinned upstream repository.

**Why this priority**: This is the smallest complete proof that the repository can build DuckDB independently from extension source code, obtain an extension as a prebuilt runtime binary, and execute an upstream test suite through an external test directory.

**Independent Test**: Trigger the workflow from a feature branch and verify that the build artifact contains DuckDB and `unittest`, contains no locally built HTTPFS extension, and that at least one upstream HTTPFS test completes successfully after `INSTALL httpfs; LOAD httpfs;`.

**Acceptance Scenarios**:

1. **Given** a supported DuckDB version and the pinned HTTPFS test commit, **When** the workflow runs, **Then** it builds only DuckDB CLI and `unittest` and publishes them as a shared artifact.
2. **Given** the shared DuckDB artifact, **When** the HTTPFS test group starts, **Then** it dynamically executes `INSTALL httpfs; LOAD httpfs;` before running upstream tests.
3. **Given** the HTTPFS repository checkout, **When** test discovery runs, **Then** tests are selected directly from the upstream checkout through `unittest --test-dir` without copying them into this repository.
4. **Given** a missing or incompatible official HTTPFS binary, **When** installation or loading fails, **Then** the test group fails and does not compile HTTPFS as a fallback.

---

### User Story 2 - Run the same CI from any branch (Priority: P1)

As a contributor, I can invoke the infrastructure workflow from any branch so that feature work can be tested before it is merged into `main`.

**Why this priority**: The infrastructure itself must be testable during development. A workflow restricted to one named branch would prevent Spec Kit feature branches and future maintenance branches from validating their changes.

**Independent Test**: Push the workflow to a branch whose name is not known in advance and verify that GitHub Actions creates a run. Also verify manual invocation and pull-request invocation.

**Acceptance Scenarios**:

1. **Given** any branch containing the workflow, **When** a commit is pushed, **Then** the workflow is eligible to run without a `branches` or `branches-ignore` filter.
2. **Given** a pull request from any branch, **When** the pull request is opened or updated, **Then** the workflow is eligible to run.
3. **Given** the workflow in the repository, **When** an authorized user selects `workflow_dispatch`, **Then** the workflow can be invoked manually.
4. **Given** the workflow source, **When** it is reviewed, **Then** no branch name is embedded in trigger conditions, job conditions, concurrency rules, paths, scripts, or artifact names.

---

### User Story 3 - Provision HTTPFS test services reproducibly (Priority: P2)

As a test maintainer, I can provision the external services required by the selected HTTPFS tests using a dedicated adapter while reusing the same DuckDB build artifact.

**Why this priority**: HTTPFS provides a useful first integration test because its upstream suite exercises HTTP, proxy, and S3-compatible behavior. This validates the adapter model required later for PostgreSQL, SQL Server, Iceberg catalogs, and other service-backed extensions.

**Independent Test**: Start the HTTPFS adapter, verify each declared health check, run the selected test group, and confirm that teardown occurs even when tests fail.

**Acceptance Scenarios**:

1. **Given** the HTTPFS test job, **When** the adapter starts, **Then** it provisions a local Python HTTP server, a Squid HTTP proxy, and the S3-compatible test service required by the selected upstream tests.
2. **Given** the services are starting, **When** readiness checks do not succeed within their declared timeout, **Then** the job fails as an infrastructure error before SQLLogicTests run.
3. **Given** healthy services, **When** the test runner starts, **Then** it receives the environment variables and generated fixture values expected by the pinned HTTPFS suite.
4. **Given** a completed, failed, or cancelled test run, **When** cleanup executes, **Then** service logs and test evidence are retained while service processes and containers are stopped.

---

### User Story 4 - Reuse the infrastructure for future extensions (Priority: P3)

As a maintainer, I can add another extension test group without rewriting the DuckDB build job or coupling that group to HTTPFS-specific services.

**Why this priority**: HTTPFS is only the first validation target. The feature must establish reusable contracts rather than a one-off workflow.

**Independent Test**: Define a second synthetic manifest entry or adapter fixture and verify that the generated test-group description can coexist with HTTPFS while still referencing the same DuckDB build artifact.

**Acceptance Scenarios**:

1. **Given** a new manifest entry, **When** its adapter is `none`, **Then** it can reuse the shared DuckDB artifact without starting HTTPFS services.
2. **Given** a service-backed extension such as PostgreSQL, **When** a dedicated adapter is added later, **Then** it can start its own service namespace and connection string without changing the HTTPFS adapter.
3. **Given** multiple enabled extensions, **When** any test group runs, **Then** every enabled extension is installed and loaded before that group’s tests, while only the owner group’s services and tests are selected.

### Edge Cases

- The official extension repository does not provide HTTPFS for the selected DuckDB version or platform.
- The HTTPFS test-source commit does not match the extension revision distributed for the selected DuckDB version.
- Test discovery returns zero files because the upstream directory layout changed.
- `INSTALL httpfs` succeeds by reusing a globally installed extension from the runner instead of the intended isolated environment.
- One service starts but another remains unhealthy.
- A port required by the adapter is already in use.
- A test requires public cloud credentials or unrestricted internet access that the standard CI profile intentionally does not provide.
- A slow or credential-dependent upstream test is excluded without a documented reason.
- The shared DuckDB artifact is missing, corrupted, or built for a different platform.
- Two parallel test groups attempt to reuse the same writable directory, port, container name, or secret directory.
- The workflow is copied to a differently named branch and silently stops triggering because of an accidental branch filter.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The feature MUST create a Spec Kit-compatible CI infrastructure that compiles only DuckDB CLI and DuckDB `unittest`.
- **FR-002**: The build stage MUST NOT compile, statically link, dynamically build, package, or publish HTTPFS or any other extension.
- **FR-003**: The build stage MUST produce a reusable artifact containing the DuckDB CLI, `unittest`, build metadata, and checksums.
- **FR-004**: The HTTPFS test stage MUST download and use the shared DuckDB artifact rather than rebuilding DuckDB.
- **FR-005**: The HTTPFS runtime binary MUST be obtained through the configured prebuilt extension source and loaded with explicit SQL statements equivalent to `INSTALL httpfs; LOAD httpfs;`.
- **FR-006**: The runtime MUST use isolated HOME, extension, temporary, database, and secret directories so that global runner state cannot satisfy installation or loading.
- **FR-007**: The HTTPFS source repository MUST be checked out at an immutable commit SHA used only for tests, fixtures, and infrastructure scripts.
- **FR-008**: For DuckDB `v1.5.4`, the initial HTTPFS test source MUST be `https://github.com/duckdb/duckdb-httpfs` at commit `c3f215ab360f04dc3d3d5305fa81849c0121f111`, unless the selected DuckDB target configuration explicitly overrides it.
- **FR-009**: SQLLogicTests MUST be executed directly from the HTTPFS checkout through DuckDB `unittest` using an external test root such as `--test-dir`.
- **FR-010**: The implementation MUST fail when test discovery returns zero expected HTTPFS tests.
- **FR-011**: The HTTPFS adapter MUST support provisioning the local HTTP server, Squid proxy, and S3-compatible service needed by the selected standard integration profile.
- **FR-012**: Every external service MUST have an explicit readiness check and timeout.
- **FR-013**: Infrastructure setup failures MUST be reported separately from functional SQLLogicTest failures.
- **FR-014**: The standard profile MUST declare include and exclude patterns for HTTPFS tests and MUST document every excluded slow, cloud-credential, unsupported-platform, or nondeterministic test.
- **FR-015**: Before tests run, the job MUST verify through `duckdb_extensions()` that HTTPFS is installed and loaded from the expected repository source.
- **FR-016**: The job MUST verify that no locally produced `httpfs.duckdb_extension` exists in the shared build artifact or workspace build outputs.
- **FR-017**: The workflow MUST be triggered by `push`, `pull_request`, and `workflow_dispatch` without branch-name filters.
- **FR-018**: The workflow MUST NOT contain hard-coded branch names in trigger filters, job-level `if` expressions, scripts, concurrency keys, artifact names, or test selection logic.
- **FR-019**: Concurrency cancellation MAY distinguish workflow and ref dynamically, but MUST work for arbitrary branch names.
- **FR-020**: Test-group jobs MUST use isolated writable directories and service namespaces so they can run safely in parallel.
- **FR-021**: The infrastructure MUST preserve logs for DuckDB build, extension installation, service startup/readiness, test discovery, test execution, and cleanup.
- **FR-022**: The workflow MUST publish a machine-readable result and a human-readable GitHub job summary even when setup or tests fail.
- **FR-023**: The implementation MUST derive the HTTPFS group from the version-controlled extension manifest rather than duplicating its repository, commit, SQL statements, and test filters throughout the workflow.
- **FR-024**: The generic build and test-group contracts MUST permit future extension entries and adapters without modifying the rule that only DuckDB is compiled.
- **FR-025**: Every HTTPFS test group MUST install and load the complete enabled extension set from the manifest before selecting and running HTTPFS-owned tests.

### Key Entities

- **DuckDB Target**: The repository, version or commit, platform, build profile, compiler settings, and allowed build targets (`duckdb` and `unittest`).
- **Shared DuckDB Artifact**: The immutable output of one build job, including binaries, metadata, and checksums reused by test groups.
- **Extension Manifest Entry**: The extension name, prebuilt binary source, install/load statements, pinned test repository and commit, test groups, filters, timeouts, and adapter reference.
- **Test Group**: A parallelizable unit that selects one upstream test subset while loading the full enabled extension set.
- **Infrastructure Adapter**: Reproducible setup, readiness, environment, fixture, logging, and teardown behavior for services required by a test group.
- **HTTPFS Adapter**: The first adapter implementation, covering a local HTTP server, Squid proxy, S3-compatible test service, expected environment variables, and service evidence.
- **Test Evidence**: Build metadata, installed extension inventory, service status, discovered tests, executed tests, skips, failures, logs, and exit classifications.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A push to a branch with an arbitrary name creates an eligible workflow run without changing the workflow file.
- **SC-002**: A complete workflow run contains exactly one DuckDB build job for each platform/build-profile matrix entry, regardless of the number of test groups.
- **SC-003**: The shared artifact contains executable DuckDB CLI and `unittest` binaries and contains zero locally built `.duckdb_extension` files.
- **SC-004**: The HTTPFS test group demonstrates that `INSTALL httpfs; LOAD httpfs;` succeeds in an isolated environment and records the installed version and source.
- **SC-005**: The HTTPFS test group discovers at least one test from the pinned upstream checkout and executes it through `--test-dir`.
- **SC-006**: All required HTTPFS services either become healthy within their declared timeout or cause a clearly classified infrastructure failure before test execution.
- **SC-007**: Build, service, discovery, installation, and test logs are available as workflow artifacts after both successful and failed runs.
- **SC-008**: Re-running the same commit with caches disabled uses the same pinned sources and produces an equivalent test inventory.
- **SC-009**: Adding a future manifest entry does not require duplicating or changing the DuckDB build implementation.
- **SC-010**: Review of the workflow finds zero literal repository branch names used as execution filters.

## Assumptions

- Linux `amd64` is the first implementation platform.
- DuckDB and `extension-ci-tools` initially remain pinned to `v1.5.4`.
- The official DuckDB extension repository provides the prebuilt HTTPFS binary for the selected DuckDB version and platform.
- The HTTPFS commit `c3f215ab360f04dc3d3d5305fa81849c0121f111` is the test revision declared by DuckDB `v1.5.4`.
- The first profile may exclude slow tests and tests requiring real public-cloud credentials, provided exclusions are explicit and evidenced.
- HTTPFS upstream scripts may be reused to provision test services, but no command may invoke the HTTPFS extension build.
- The implementation phase will decide the exact artifact layout and machine-readable report format while preserving the contracts in this specification.
- This feature establishes infrastructure and one real test group; support for additional extensions remains future work.
