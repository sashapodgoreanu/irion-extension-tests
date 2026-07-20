<!--
Sync Impact Report

- Version change: 1.0.0 -> 1.0.1
- Clarified the non-negotiable build boundary: this repository compiles only DuckDB and its unittest runner; it never compiles extension source code.
- Removed the previous exception that allowed controlled extension compilation.
- Replaced the planned "production FTS adapter" wording with an FTS test-group implementation that installs the official binary.
- Dependent artifacts added or updated with this constitution:
  - README.md
  - config/extensions.yml
  - docs/ci-architecture.md
- Follow-up implementation work:
  - define and validate the manifest schema;
  - implement the build-once/fan-out GitHub Actions workflow;
  - implement the first test group using FTS tests and the official FTS binary;
  - add service-backed adapters such as PostgreSQL.
-->

# Irion DuckDB Extension QA Constitution

## Core Principles

### I. QA Harness, Not a Product Extension

This repository MUST exist only as a quality-assurance harness for the set of DuckDB extensions used by Irion. It may retain a fictitious extension-project shape when useful for DuckDB tooling, but it MUST NOT implement, compile, package, publish, or distribute any DuckDB extension.

The only native product this repository is allowed to compile is DuckDB itself, including the DuckDB CLI and the `unittest` executable required to run SQLLogicTests. Extension source code MUST never be added to the DuckDB build graph.

The harness MUST orchestrate DuckDB builds, extension installation and loading, external service setup, upstream test discovery, test execution, and evidence collection. Extension source code and extension-owned test suites MUST remain in their original repositories.

### II. Declarative and Pinned Extension Inventory

A version-controlled manifest MUST be the single source of truth for every extension included in the compatibility suite. Each enabled extension MUST declare, at minimum:

- its canonical name;
- its source repository;
- an immutable commit SHA for the test sources;
- the repository or artifact source from which its prebuilt runtime binary is installed;
- the SQL statements required to install and load it;
- the upstream test roots and include/exclude patterns;
- the adapter or infrastructure profile required by its tests;
- relevant timeouts and explicitly justified skips.

Branches and mutable tags MAY be used during exploration, but the official compatibility pipeline MUST resolve and record immutable commit SHAs. Adding or removing an extension MUST be performed through the manifest and reviewed as a change to the supported Irion runtime surface.

### III. Compile DuckDB Only, Once; Fan Out Test Groups

For each DuckDB version, platform, architecture, and build profile, the pipeline MUST compile only DuckDB, the DuckDB CLI, and its `unittest` executable. It MUST NOT configure, generate, or build extension targets, loadable-extension targets, static-extension targets, extension repositories, or extension-owned native dependencies.

The pipeline MUST build DuckDB exactly once for each matrix entry. The resulting binaries MUST be published as immutable workflow artifacts and reused by all extension test groups for that matrix entry.

After the shared build succeeds, one independent test job MUST be generated for each declared extension or test group. These jobs SHOULD run in parallel. A test-group job MUST NOT rebuild DuckDB merely because it owns a different upstream test directory or needs different service fixtures.

A separate DuckDB build is permitted only when the target platform, compiler, build flags, storage configuration, sanitizer, or another declared matrix dimension is materially different.

### IV. All Declared Extensions Loaded for Every Test Group (NON-NEGOTIABLE)

Every test group MUST run against the complete enabled Irion extension set, not only against the extension that owns the tests being executed.

Before a test group starts, the job MUST create an isolated runtime environment, dynamically install every enabled extension from its declared prebuilt-binary source, and execute every declared `LOAD` statement. A failure to install or load any enabled extension MUST fail the group before upstream tests are run.

The owner of the test group determines which upstream tests are selected; it does not reduce the set of extensions present in the DuckDB process. This rule exists to detect conflicts that isolated extension pipelines cannot reveal, including collisions in functions, types, settings, secrets, filesystems, catalogs, global initialization, dependency versions, and load order.

Dynamic `INSTALL` and `LOAD` are the only supported extension-loading path in this repository. Extension source compilation is prohibited, including when an official binary is unavailable. In that situation the extension MUST be marked unsupported for the selected DuckDB target and the pipeline MUST fail or exclude it explicitly according to policy; it MUST NOT silently compile the extension.

### V. Upstream Test Fidelity, Never Test Copying

Tests MUST be checked out directly from each extension repository at the pinned commit and executed from that checkout. SQLLogicTests SHOULD be supplied to DuckDB `unittest` through an external test root such as `--test-dir`, preserving the upstream directory structure, fixtures, relative paths, and test metadata.

The repository MUST NOT copy, fork, or manually synchronize upstream tests into an Irion-owned test directory. Irion-specific cross-extension contracts MAY be added separately, but they MUST be clearly identified as Irion-owned tests rather than upstream coverage.

If an upstream suite uses a runner other than SQLLogicTest, the adapter MUST invoke the native runner or report that category as unsupported. The pipeline MUST NOT claim full upstream coverage when only a subset of the repository's tests was executed.

### VI. Extension-Specific Adapters and Infrastructure

Each extension MAY declare an adapter that prepares only the infrastructure needed by its own test group while preserving the common all-extensions-loaded runtime.

An adapter MAY define:

- containers or Docker Compose services;
- service images pinned to immutable versions or digests;
- startup and teardown commands;
- health checks and readiness timeouts;
- fixture generation;
- environment variables;
- connection strings passed to the upstream tests;
- credentials obtained from GitHub secrets;
- platform restrictions;
- test-specific include, exclude, and timeout rules.

For example, a PostgreSQL-backed extension test group MAY start a PostgreSQL container, wait for readiness, create fixtures, and expose a connection string to the upstream PostgreSQL tests. Infrastructure setup MUST remain isolated to that group and MUST be reproducible from the adapter definition. An adapter MUST never compile the extension under test.

### VII. Fail Closed and Produce Evidence

The pipeline MUST fail closed. Missing extensions, failed `INSTALL` or `LOAD` statements, empty test discovery, unexpected skips, missing fixtures, service readiness failures, crashes, and timeouts MUST NOT be converted into successful runs.

Each test-group artifact MUST record enough evidence to reproduce and diagnose the result, including:

- DuckDB version and commit;
- extension names, source repositories, and pinned commits;
- installed extension versions and installation sources;
- proof that all enabled extensions were loaded;
- the exact test directory and selection filters;
- service and adapter configuration with secrets redacted;
- discovered, executed, skipped, passed, failed, crashed, and timed-out tests;
- stdout, stderr, exit codes, and relevant generated configuration.

Functional failures and infrastructure failures MUST be classified separately. Every skip MUST have a documented reason, owner, scope, and optional expiry condition.

### VIII. Reproducibility and Safe Evolution

Compatibility results MUST be reproducible from committed configuration. The pipeline MUST use isolated HOME, extension, temporary, and database directories so that globally installed extensions or files from previous runs cannot influence a result.

Workflow actions, source repositories, test commits, DuckDB versions, CI tooling, container images, and service images MUST be pinned for official runs. Caches MAY accelerate the DuckDB build, but deleting all caches MUST NOT change correctness.

Adding a new extension MUST be incremental: add one manifest entry, add an adapter only when needed, validate discovery, prove dynamic installation and loading, and run its group with the complete enabled extension set. Existing extension groups MUST continue to run unchanged unless the manifest deliberately changes the supported runtime.

## Technical Constraints

- The first supported CI platform is Linux `amd64`; the design MUST remain portable to Windows and other DuckDB-supported platforms.
- DuckDB and `extension-ci-tools` versions MUST be independently configurable and pinned.
- The build stage MUST contain no extension source checkout and no extension CMake configuration.
- Prebuilt extension binaries MUST be installed from a repository compatible with the selected DuckDB version.
- Test-source commits SHOULD match the extension revision declared by the selected DuckDB release when that mapping exists.
- Network access MAY be used during checkout and `INSTALL`, but test execution MUST record every externally obtained artifact and MUST NOT silently fall back to a different source.
- Secrets MUST never be committed to the manifest, generated reports, logs, or test artifacts.
- Parallel test groups MUST use independent writable directories and independent service namespaces.
- Irion-owned cross-extension smoke tests MUST verify at least extension inventory, installation source, load success, multiple connections, and deterministic load order.

## Development Workflow and Quality Gates

Every feature specification and implementation plan MUST include a Constitution Check confirming compliance with these principles.

Adding or changing an extension requires the following sequence:

1. Add or update its manifest entry with an immutable source commit.
2. Define its prebuilt-binary source and install/load statements.
3. Define its upstream test roots and discovery patterns.
4. Add an adapter only when external services or custom setup are required.
5. Validate that the shared DuckDB build is reused rather than rebuilt.
6. Prove that no extension source or extension target is present in the build stage.
7. Prove that all enabled extensions install and load before the new test group starts.
8. Prove that at least one expected upstream test is discovered, unless an explicit no-tests contract exists.
9. Publish logs and machine-readable results.
10. Verify that existing extension groups still run with the expanded all-loaded set.

A pipeline is eligible to pass only when:

- the manifest is valid;
- all enabled sources and tools are pinned;
- the shared DuckDB-only build succeeds;
- no extension was compiled by this repository;
- all enabled extensions are installed and loaded in every test group;
- every enabled test group discovers its expected tests;
- all required services become healthy;
- all unskipped tests complete successfully;
- all skips are declared and justified;
- evidence artifacts are published.

## Governance

This constitution supersedes implementation convenience, legacy extension-template conventions, and extension-specific shortcuts. Specifications, plans, tasks, CI workflows, adapters, and code reviews MUST explicitly comply with it.

Amendments require:

1. a documented rationale;
2. an impact assessment for manifests, adapters, workflows, and existing extension groups;
3. a semantic version change to this constitution;
4. migration guidance when an established contract changes.

Versioning follows semantic versioning:

- MAJOR: removal or incompatible redefinition of a governing principle;
- MINOR: a new principle or materially expanded mandatory behavior;
- PATCH: clarification without changing required behavior.

Compliance SHOULD be reviewed whenever DuckDB, extension-ci-tools, the manifest schema, or the CI execution model changes.

**Version**: 1.0.1 | **Ratified**: 2026-07-20 | **Last Amended**: 2026-07-20
