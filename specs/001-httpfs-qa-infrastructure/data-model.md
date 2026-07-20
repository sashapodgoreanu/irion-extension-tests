# Data Model: HTTPFS QA Infrastructure

**Feature**: `001-httpfs-qa-infrastructure`  
**Date**: 2026-07-20

This feature is configuration- and artifact-driven. The entities below describe the committed manifest, normalized workflow inputs, generated runtime configuration, and evidence outputs.

## 1. DuckDB Target

Represents one DuckDB build matrix entry.

| Field | Type | Required | Description |
|---|---|---:|---|
| `name` | string | yes | Stable identifier such as `duckdb-1.5.4-linux-amd64-release`. |
| `repository` | URI | yes | Canonical DuckDB Git repository. |
| `ref` | string | yes | Pinned tag or immutable commit for DuckDB. Official runs record the resolved commit. |
| `ci_tools.repository` | URI | yes | Canonical `extension-ci-tools` repository. |
| `ci_tools.ref` | string | yes | Pinned CI-tools reference. |
| `platform` | string | yes | DuckDB platform identifier, initially `linux_amd64`. |
| `runner` | string | yes | GitHub runner label, initially `ubuntu-24.04`. |
| `build_type` | enum | yes | Initially `Release`. |
| `targets` | set | yes | Must contain exactly `duckdb` and `unittest`. |
| `toolchain_image` | object | yes | Pinned source/build inputs for the official toolchain container. |
| `build_options` | map | no | Approved DuckDB-only CMake options. Must not reference tested extensions. |

### Validation rules

- `targets` contains no extension target.
- No field may declare an extension `SOURCE_DIR`, extension config, or loadable/static extension target.
- `repository`, `ref`, platform, and resolved commit are written to build evidence.
- One shared build artifact is produced for each unique DuckDB Target.

## 2. Shared DuckDB Artifact

Represents the immutable output consumed by all test groups for one DuckDB Target.

| Field | Type | Required | Description |
|---|---|---:|---|
| `artifact_name` | string | yes | Deterministic name based on target and source commit, never a literal branch name. |
| `duckdb_binary` | path | yes | Relative path `bin/duckdb`. |
| `unittest_binary` | path | yes | Relative path `bin/unittest`. |
| `runtime_libraries` | array[path] | no | Non-system libraries required after relocation. |
| `build_metadata` | path | yes | `metadata/build.json`. |
| `checksums` | path | yes | `checksums/SHA256SUMS`. |
| `source_commit` | SHA | yes | Resolved DuckDB commit. |
| `platform` | string | yes | Platform encoded in the artifact. |
| `created_by_run` | string | yes | GitHub run identifier for traceability. |

### State transitions

```text
PLANNED -> BUILDING -> VALIDATING -> PUBLISHED
                    \-> FAILED
```

`VALIDATING` includes artifact inspection, `.duckdb_extension` rejection, checksum generation, extraction to a clean directory, and execution smoke tests.

## 3. Extension Manifest Entry

Represents an extension in the Irion compatibility composition.

| Field | Type | Required | Description |
|---|---|---:|---|
| `name` | string | yes | DuckDB extension identifier, for example `httpfs`. |
| `enabled` | boolean | yes | Whether the extension participates in every test-group runtime. |
| `runtime.binary_source` | enum | yes | Initially `official_duckdb_repository`; extensible to approved prebuilt repositories. |
| `runtime.repository` | URI/string | conditional | Explicit custom prebuilt repository when not official. |
| `runtime.install_statements` | array[string] | yes | Explicit SQL installation commands. |
| `runtime.load_statements` | array[string] | yes | Explicit SQL load commands. |
| `test_source.repository` | URI | yes | Canonical upstream test repository. |
| `test_source.commit` | SHA-40 | yes | Immutable test/fixture/script revision. |
| `test_groups` | array[Test Group] | yes | One or more independently executable upstream groups. |

### Validation rules

- Every enabled entry has at least one install statement and one load statement.
- Test source commit must be a full 40-character hexadecimal SHA.
- No entry may define build commands or source-build targets.
- An enabled extension is installed and loaded in every generated Test Group, regardless of ownership.

## 4. Setup-Only Runtime Tool

Represents a prebuilt extension or executable used only to prepare fixtures.

| Field | Type | Required | Description |
|---|---|---:|---|
| `name` | string | yes | Tool identifier, for example `tpch`. |
| `purpose` | string | yes | Human-readable fixture/setup reason. |
| `install_statements` | array[string] | conditional | Dynamic installation statements when the tool is a DuckDB extension. |
| `load_statements` | array[string] | conditional | Load statements used only during adapter setup. |
| `scope` | const | yes | Must be `adapter_setup_only`. |

### Validation rules

- A setup-only tool is not appended to the enabled Irion extension set.
- It is recorded separately in evidence.
- It must be prebuilt; local compilation is prohibited.

## 5. Test Group

Represents one parallelizable test unit owned by one extension.

| Field | Type | Required | Description |
|---|---|---:|---|
| `name` | string | yes | Globally unique group name, initially `httpfs-standard`. |
| `owner_extension` | string | yes | Manifest extension that owns the selected tests. |
| `runner` | enum | yes | Initially `duckdb_unittest`. |
| `test_dir` | path | yes | Root passed to `--test-dir`, relative to checkout. |
| `include` | array[glob] | yes | Upstream tests eligible for selection. |
| `exclude` | array[Exclusion] | yes | Explicitly documented exclusions. |
| `include_slow` | boolean | yes | Whether `.test_slow` is eligible. |
| `timeout_seconds` | integer | yes | Hard group timeout. |
| `adapter` | string | yes | Adapter name, initially `httpfs`. |
| `environment` | map[string,string] | no | Non-secret environment contract or variable references. |
| `minimum_executed_tests` | integer | yes | Must be at least `1` for HTTPFS. |

### Derived fields

The normalized matrix adds:

- resolved owner repository and commit;
- complete enabled extension install/load statement lists;
- adapter implementation path;
- DuckDB artifact selector;
- isolated namespace identifier;
- report/artifact name.

### State transitions

```text
QUEUED
  -> ARTIFACT_READY
  -> SOURCE_READY
  -> ADAPTER_SETUP
  -> SERVICES_READY
  -> EXTENSIONS_INSTALLED
  -> EXTENSIONS_LOADED
  -> TESTS_DISCOVERED
  -> TESTS_RUNNING
  -> REPORTING
  -> SUCCEEDED
```

Failure terminal states:

```text
CONFIGURATION_FAILED
ARTIFACT_FAILED
INFRASTRUCTURE_FAILED
EXTENSION_INSTALL_FAILED
EXTENSION_LOAD_FAILED
EMPTY_DISCOVERY
FUNCTIONAL_FAILED
TIMED_OUT
CRASHED
CLEANUP_FAILED
```

A cleanup failure is recorded independently and may convert an otherwise successful group into a failed result according to policy.

## 6. Test Exclusion

Represents one explicit non-selection rule.

| Field | Type | Required | Description |
|---|---|---:|---|
| `pattern` | glob/path | yes | Upstream path or pattern. |
| `category` | enum | yes | `slow`, `cloud_credentials`, `unsupported_platform`, `nondeterministic_external`, or `known_upstream_issue`. |
| `reason` | string | yes | Specific justification. |
| `owner` | string | yes | Maintainer/team responsible for review. |
| `expires` | date/string | no | Review date, DuckDB version, or issue condition. |

### Validation rules

- Bare exclusion strings are not allowed in the normalized schema.
- Every excluded discovered test appears in the evidence inventory.
- Expired exclusions fail validation or emit a blocking policy result.

## 7. Infrastructure Adapter Definition

Represents reusable service lifecycle configuration.

| Field | Type | Required | Description |
|---|---|---:|---|
| `name` | string | yes | Adapter identifier. |
| `implementation` | path | yes | Repository-relative adapter directory. |
| `setup_timeout_seconds` | integer | yes | Overall setup timeout. |
| `readiness_timeout_seconds` | integer | yes | Overall readiness timeout. |
| `teardown_timeout_seconds` | integer | yes | Cleanup timeout. |
| `services` | array[Service Definition] | yes | Required service declarations. |
| `setup_tools` | array[Setup-Only Runtime Tool] | no | Fixture-generation dependencies. |
| `required_host_capabilities` | array[string] | no | For HTTPFS: Docker, Compose, sudo, loopback networking. |

### HTTPFS instance

The first adapter contains three services:

1. `python-http`;
2. `squid`;
3. `minio-s3`.

It also prepares host aliases, fixtures, presigned URLs, and the environment expected by the pinned HTTPFS test suite.

## 8. Service Definition

| Field | Type | Required | Description |
|---|---|---:|---|
| `name` | string | yes | Stable service name. |
| `kind` | enum | yes | `process` or `container_stack`. |
| `image` | string | conditional | Pinned image digest for containers. |
| `command` | string/array | conditional | Start command or Compose invocation. |
| `ports` | array[integer] | no | Declared ports. |
| `healthcheck` | Health Check | yes | Probe definition. |
| `log_paths` | array[path] | yes | Files/commands collected as evidence. |
| `stop_command` | string/array | yes | Deterministic teardown command. |

## 9. Health Check

| Field | Type | Required | Description |
|---|---|---:|---|
| `type` | enum | yes | `tcp`, `http`, `command`, or `container_log`. |
| `target` | string | yes | Host/port, URL, command, or log expression. |
| `interval_seconds` | integer | yes | Poll interval. |
| `timeout_seconds` | integer | yes | Per-probe timeout. |
| `attempts` | integer | yes | Maximum attempts. |

A failed health check produces `INFRASTRUCTURE_FAILED` before test discovery.

## 10. Generated Test Configuration

Represents the JSON passed to DuckDB `unittest`.

| Field | Type | Required | Description |
|---|---|---:|---|
| `autoloading` | const | yes | `none`. |
| `on_init` | SQL string | yes | Deterministic ordered `LOAD` statements for all enabled extensions. |
| `on_new_connection` | SQL string | no | Used only when runner semantics require connection-specific initialization. |
| `summarize_failures` | boolean | yes | `true`. |
| `skip_tests` | array[path] | no | Generated only from structured manifest exclusions. |
| `test_env` | object | no | Non-secret generated variables consumed by upstream tests. |

### Validation rules

- Contains no `INSTALL` statement after the isolated preinstall phase.
- Contains every enabled extension exactly once in deterministic order.
- Contains no branch-derived values.
- Generated file is preserved in Test Evidence.

## 11. Test Evidence

Represents the complete result artifact for a Test Group.

| Field | Type | Required | Description |
|---|---|---:|---|
| `result.json` | JSON | yes | Machine-readable classification and counts. |
| `summary.md` | Markdown | yes | Human-readable summary. |
| `manifest.normalized.json` | JSON | yes | Exact normalized configuration used. |
| `extensions.json` | JSON | yes | Installed/loaded inventory and sources. |
| `tests.discovered.txt` | text | yes | All discovered owner tests. |
| `tests.selected.txt` | text | yes | Tests selected after filters. |
| `tests.excluded.json` | JSON | yes | Structured exclusions and reasons. |
| `unittest.log` | text | conditional | Test output when execution starts. |
| `services/` | directory | conditional | Adapter setup/readiness/runtime logs. |
| `generated-test-config.json` | JSON | yes | Exact runner configuration. |
| `commands.log` | text | yes | Sanitized commands and exit codes. |

### Result counters

- discovered;
- selected;
- excluded;
- skipped;
- executed;
- passed;
- failed;
- timed_out;
- crashed.

Secrets are redacted before any evidence file is persisted.

## Relationships

```text
DuckDB Target
    1 ───── 1 Shared DuckDB Artifact
                    │
                    └──── used by ──── * Test Group

Extension Manifest Entry
    1 ───── * Test Group (ownership)
    * ───── * Test Group (enabled runtime composition)

Test Group
    * ───── 1 Infrastructure Adapter Definition
    1 ───── * Test Exclusion
    1 ───── 1 Generated Test Configuration
    1 ───── 1 Test Evidence

Infrastructure Adapter Definition
    1 ───── * Service Definition
    1 ───── * Setup-Only Runtime Tool
```
