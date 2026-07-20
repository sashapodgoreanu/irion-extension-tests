# Contract: Infrastructure Adapter Lifecycle

**Feature**: `001-httpfs-qa-infrastructure`  
**Version**: 1

An infrastructure adapter prepares and tears down only the services required by one test group. It never builds DuckDB or an extension and never changes the complete enabled extension set.

## Adapter Directory

Each adapter is a repository directory with this interface:

```text
scripts/qa/adapters/<adapter-name>/
├── setup.sh
├── readiness.sh
├── environment.sh
└── teardown.sh
```

Optional helper files may live below the adapter directory, but the four lifecycle entry points are mandatory.

## Common Inputs

The generic test-group runner provides these environment variables to every phase:

| Variable | Description |
|---|---|
| `QA_ADAPTER_NAME` | Manifest adapter identifier. |
| `QA_RUN_NAMESPACE` | Unique, filesystem-safe job namespace. |
| `QA_WORKSPACE` | Repository workspace root. |
| `QA_DUCKDB_BIN` | Absolute path to the shared DuckDB CLI. |
| `QA_UNITTEST_BIN` | Absolute path to the shared `unittest`. |
| `QA_TEST_SOURCE_DIR` | Absolute path to the pinned owner-extension checkout. |
| `QA_RUNTIME_HOME` | Isolated HOME used for extension installation and test execution. |
| `QA_EXTENSION_DIR` | Isolated DuckDB extension directory. |
| `QA_TEMP_DIR` | Isolated temporary directory. |
| `QA_SECRET_DIR` | Isolated DuckDB secret directory. |
| `QA_SERVICE_DIR` | Adapter-owned service state directory. |
| `QA_REPORT_DIR` | Directory where the adapter must preserve evidence. |
| `QA_ADAPTER_CONFIG` | Absolute path to normalized adapter JSON. |
| `QA_GROUP_CONFIG` | Absolute path to normalized test-group JSON. |
| `QA_ENV_FILE` | Absolute path where `environment.sh` writes exported variables. |

Secrets are passed through secret-specific environment variables and must never be written unredacted to `QA_REPORT_DIR`.

## Phase 1: `setup.sh`

### Purpose

Create required directories, install host packages when allowed, configure host aliases, start processes or containers, and generate fixtures that do not require service readiness.

### Requirements

- Must be idempotent within one run namespace.
- Must not invoke DuckDB, HTTPFS, or any tested extension build.
- Must reject or avoid `make`, CMake, Ninja, extension CMake configuration, and local `.duckdb_extension` production.
- Must use only the adapter's service namespace and state directories.
- Must write commands, process IDs, container project names, and initial logs to the report directory.
- Must return before the configured setup timeout.

### Exit codes

| Code | Meaning |
|---:|---|
| `0` | Setup commands completed; services may still be starting. |
| `10` | Invalid adapter configuration or missing host capability. |
| `20` | Package, process, container, network, host-alias, or fixture setup failure. |
| `22` | Fixture-generation failure. |

## Phase 2: `readiness.sh`

### Purpose

Block until every declared service is ready or its timeout expires.

### Requirements

- Evaluate every service health check independently.
- Produce a machine-readable readiness result for each service.
- Include probe type, target, attempts, elapsed time, and final status.
- Fail before extension installation and test discovery when any required service is unhealthy.
- Never silently downgrade a required service to optional.

### Exit codes

| Code | Meaning |
|---:|---|
| `0` | All required services are healthy. |
| `21` | At least one service failed readiness. |

## Phase 3: `environment.sh`

### Purpose

Publish the environment needed by upstream tests after services and fixtures are ready.

### Output

Write a UTF-8 dotenv-style file to `QA_ENV_FILE`:

```text
NAME=value
OTHER_NAME=value
```

### Requirements

- Variable names must match `^[A-Z][A-Z0-9_]*$`.
- Values must be single-line and safely escaped by the generic runner.
- Secret values may be exported for the current process but must be redacted from evidence.
- The adapter must not mutate the parent shell directly; the generic runner validates and imports the file.
- All non-secret variables and all redacted secret names are copied into evidence.

### Exit codes

| Code | Meaning |
|---:|---|
| `0` | Environment file written and complete. |
| `10` | Invalid/missing configuration. |
| `23` | Required environment or generated value unavailable. |

## Phase 4: Test Execution

The generic runner, not the adapter:

1. installs all enabled prebuilt extensions;
2. loads all enabled extensions;
3. generates the DuckDB test config;
4. discovers the owner tests;
5. executes `unittest --test-dir`.

The adapter may not replace or wrap the test runner except through declared environment and services.

## Phase 5: `teardown.sh`

### Purpose

Collect final logs and stop/remove all adapter-owned processes, containers, networks, and temporary service state.

### Requirements

- Invoked through an unconditional shell trap and an Actions `always()` path.
- Safe when setup failed partially.
- Must target only resources containing `QA_RUN_NAMESPACE` or recorded ownership metadata.
- Must preserve service logs before stopping resources when possible.
- Must not delete the generic test report directory.
- Must return before the teardown timeout.

### Exit codes

| Code | Meaning |
|---:|---|
| `0` | Evidence collected and resources stopped. |
| `30` | Cleanup or final evidence collection failed. |

A teardown failure is reported separately. Policy may fail the group even when functional tests passed.

## Evidence Contract

Each adapter writes under:

```text
${QA_REPORT_DIR}/services/<adapter-name>/
```

Required files:

```text
configuration.redacted.json
setup.log
readiness.json
runtime-environment.redacted.json
teardown.log
resource-inventory.json
```

Each service should additionally provide its native logs or a documented reason why no log exists.

## HTTPFS Adapter Requirements

The `httpfs` adapter must provide:

### Python HTTP server

- Serve an adapter-controlled fixture directory.
- Default compatibility endpoint equivalent to `http://localhost:8008` unless dynamically overridden and exported.
- Readiness probe performs an HTTP request to a known fixture.
- PID and access/error logs are recorded.

### Squid proxy

- Use the pinned upstream proxy configuration behavior or an adapter-owned generated configuration.
- Default compatibility endpoint equivalent to `localhost:3128` unless dynamically overridden and exported.
- Readiness probe verifies both TCP acceptance and one proxied HTTP request.
- Squid logs are preserved.

### MinIO/S3-compatible service

- Use a pinned image digest or pinned upstream Compose definition whose images resolve to approved digests.
- Use a unique Compose project name derived from `QA_RUN_NAMESPACE`.
- Configure required host aliases such as `duckdb-minio.com` and bucket subdomains.
- Wait for the upstream initialization marker and an active S3 health operation.
- Export the AWS test credentials, endpoint, region, SSL mode, presigned URLs, and availability flags expected by the selected suite.
- Preserve container logs and the resolved Compose configuration.

### Fixture generation

- Use the shared DuckDB CLI.
- May dynamically install prebuilt setup-only tools declared by the adapter, initially `tpch`.
- Must not compile fixture tools or HTTPFS.
- Must preserve fixture-generation SQL, commands, extension inventory, and checksums.

## Security Rules

- No secret is committed or uploaded unredacted.
- Test credentials must be local, ephemeral, and limited to the isolated service stack.
- Container/service names and host paths must be generated from validated inputs.
- Adapter scripts must quote all paths and use strict shell mode.
- Upstream scripts are executed only from the manifest-pinned checkout and only after a policy scan confirms they do not trigger extension builds.
