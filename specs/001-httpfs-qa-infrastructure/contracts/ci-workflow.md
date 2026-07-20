# Contract: GitHub Actions QA Workflow

**Feature**: `001-httpfs-qa-infrastructure`  
**Version**: 1

The workflow implements one manifest-validation stage, one shared DuckDB build per build matrix entry, and one parallel job per declared test group.

## Workflow Location

```text
.github/workflows/extension-qa.yml
```

## Trigger Contract

The workflow must be eligible for every repository branch and pull request.

Required events:

```yaml
on:
  push:
  pull_request:
  workflow_dispatch:
```

Forbidden anywhere in the workflow or invoked scripts:

- `branches`;
- `branches-ignore`;
- literal comparisons with `main`, the feature branch, or another repository branch;
- branch-specific path selection;
- artifact names containing a branch name;
- job conditions that allow only a named branch.

A contract test must parse the workflow and reject forbidden filters or literal repository branch conditions.

Manual dispatch becomes selectable for arbitrary refs after the workflow exists on the default branch. Before merge, `push` and `pull_request` validate the feature branch.

## Permissions

Default permissions must be read-only:

```yaml
permissions:
  contents: read
```

Additional permissions require a documented feature change. No package publication or repository write permission is needed.

## Concurrency

The workflow may cancel stale runs using dynamic event/ref data:

```text
<workflow-name>-<pull-request-number-or-ref>
```

The key must not contain a literal repository branch name.

## Supply-Chain Pinning

The implementation must pin:

- GitHub Actions to immutable commit SHAs;
- DuckDB and CI-tools refs from the manifest and record resolved SHAs;
- HTTPFS test source to its full commit SHA;
- Python dependencies to exact versions/hashes;
- service images to immutable digests or an approved lock file.

A workflow summary must show the resolved versions without exposing secrets.

## Job 1: `validate-manifest`

### Responsibilities

1. Check out the current repository revision.
2. Validate `config/extensions.yml` against `config/schema/extensions.schema.json`.
3. Apply semantic validation not expressible in JSON Schema:
   - unique extension names;
   - unique test-group names;
   - adapter references exist;
   - every enabled extension has installation/loading statements;
   - no build commands or extension source-build fields;
   - all test commits are immutable full SHAs;
   - exclusions are structured and not expired;
   - build targets are exactly `duckdb` and `unittest`;
   - workflow policy contains no branch filters.
4. Produce normalized manifest JSON.
5. Produce a DuckDB build matrix.
6. Produce a test-group matrix containing one entry per enabled group.
7. Upload validation evidence.

### Outputs

| Output | Description |
|---|---|
| `build_matrix` | Compact JSON matrix for DuckDB targets. |
| `test_group_matrix` | Compact JSON matrix for enabled test groups. |
| `manifest_digest` | SHA-256 of normalized manifest. |
| `normalized_manifest_artifact` | Artifact name containing normalized configuration. |

### Failure semantics

Any schema or semantic error is `CONFIGURATION_FAILED`. No build job may start.

## Job 2: `build-duckdb`

### Strategy

Use `fromJSON(needs.validate-manifest.outputs.build_matrix)`.

### Responsibilities

1. Download the normalized manifest.
2. Check out DuckDB and `extension-ci-tools` at declared refs.
3. Record resolved commits.
4. Build the pinned official `linux_amd64` toolchain container.
5. Configure standard DuckDB without external/tested extension source configuration.
6. Build only `duckdb` and `unittest`.
7. Scan the build tree and fail on locally produced tested-extension `.duckdb_extension` files.
8. Create the Shared DuckDB Artifact.
9. Verify checksums and relocation in a clean extraction directory.
10. Upload build logs and the shared artifact.

### Required artifact layout

```text
bin/duckdb
bin/unittest
metadata/build.json
checksums/SHA256SUMS
runtime-libs/                 # only when required
```

### Artifact name

Derived from target identity and resolved DuckDB commit, for example:

```text
duckdb-linux-amd64-release-<short-duckdb-sha>
```

It must not include a branch name.

### Failure semantics

- source/toolchain/configuration problem: `BUILD_INFRASTRUCTURE_FAILED`;
- compiler/linker failure: `DUCKDB_BUILD_FAILED`;
- forbidden local extension artifact: `POLICY_FAILED`;
- relocation/checksum failure: `ARTIFACT_FAILED`.

No test-group job may run without a successful matching build artifact.

## Job 3: `test-group`

### Dependencies

```text
needs: [validate-manifest, build-duckdb]
```

### Strategy

Use `fromJSON(needs.validate-manifest.outputs.test_group_matrix)` with `fail-fast: false` so one group failure does not erase evidence from unrelated groups.

### Responsibilities

1. Check out the current repository revision.
2. Download the normalized manifest.
3. Download the matching Shared DuckDB Artifact.
4. Verify artifact checksums.
5. Check out the owner extension repository at its pinned commit.
6. Create a unique isolated runtime namespace.
7. Start the declared adapter and wait for readiness.
8. Dynamically install every enabled extension from its declared prebuilt source.
9. Load every enabled extension and verify `duckdb_extensions()`.
10. Generate and preserve the test configuration.
11. Discover owner tests and apply structured include/exclude policy.
12. Fail when selected inventory is below `minimum_executed_tests`.
13. Execute the owner tests through the declared runner.
14. Normalize result classification and counters.
15. Teardown the adapter unconditionally.
16. Upload test evidence unconditionally.
17. Append a human-readable job summary.

### Runtime isolation

Each matrix job uses unique paths for:

- HOME;
- DuckDB extension installation;
- XDG cache/config/data;
- secrets;
- temporary files;
- databases;
- service volumes;
- Compose project/network names;
- reports.

No cache may restore an installed extension directory into the runtime HOME.

### Extension preflight

Before discovery, execute equivalent logic:

```sql
INSTALL httpfs;
LOAD httpfs;

SELECT extension_name,
       loaded,
       installed,
       extension_version,
       install_mode,
       installed_from
FROM duckdb_extensions()
WHERE extension_name IN (<all-enabled-extensions>);
```

The generic implementation renders statements from the normalized manifest and verifies every enabled extension, not only the group owner.

### Runner invocation

For a DuckDB SQLLogicTest group:

```text
unittest
  --test-config <generated-config>
  --test-dir <pinned-owner-checkout>
  <manifest-selection>
```

When multiple include patterns cannot be represented by one runner invocation without ambiguity, execute deterministic sub-invocations and aggregate them into one group result.

### Failure semantics

| Classification | Examples |
|---|---|
| `CONFIGURATION_FAILED` | Invalid normalized matrix, missing adapter, invalid exclusion. |
| `ARTIFACT_FAILED` | Missing/corrupt DuckDB artifact. |
| `INFRASTRUCTURE_FAILED` | Squid/HTTP/MinIO setup or readiness failure. |
| `EXTENSION_INSTALL_FAILED` | `INSTALL` fails for any enabled extension. |
| `EXTENSION_LOAD_FAILED` | `LOAD` or extension inventory assertion fails. |
| `EMPTY_DISCOVERY` | No expected upstream tests selected. |
| `FUNCTIONAL_FAILED` | One or more upstream tests fail assertions. |
| `TIMED_OUT` | Group or individual invocation exceeds timeout. |
| `CRASHED` | Signal, core dump, or abnormal runner termination. |
| `CLEANUP_FAILED` | Adapter resources cannot be stopped or evidence cannot be finalized. |

Infrastructure and functional failures must not be collapsed into one generic result.

## HTTPFS Matrix Entry

The initial group resolves approximately to:

```json
{
  "name": "httpfs-standard",
  "owner_extension": "httpfs",
  "repository": "https://github.com/duckdb/duckdb-httpfs.git",
  "commit": "c3f215ab360f04dc3d3d5305fa81849c0121f111",
  "runner": "duckdb_unittest",
  "test_dir": ".",
  "adapter": "httpfs",
  "include_slow": false,
  "minimum_executed_tests": 1
}
```

The full include/exclude lists and complete enabled extension runtime are read from normalized configuration, not duplicated in workflow YAML.

## Evidence Artifacts

### Manifest validation artifact

```text
manifest.normalized.json
build-matrix.json
test-group-matrix.json
validation.log
```

### DuckDB build evidence

```text
build.log
configure.log
toolchain.log
build.json
SHA256SUMS
ldd.txt
artifact-smoke-test.log
policy-scan.json
```

### Test-group evidence

```text
result.json
summary.md
manifest.normalized.json
owner-source.json
extensions.json
tests.discovered.txt
tests.selected.txt
tests.excluded.json
generated-test-config.json
installation.log
unittest.log
commands.log
services/
cleanup.log
```

Artifacts are uploaded with `if: always()` and use group/target/commit identifiers rather than branch names.

## Job Summary

Every run must expose:

- DuckDB ref and resolved SHA;
- CI-tools ref and resolved SHA;
- manifest digest;
- build target/platform;
- enabled extension inventory;
- owner test repository and commit;
- adapter/service readiness;
- discovered/selected/excluded/executed/passed/failed counts;
- result classification;
- artifact names.

## Acceptance Tests for the Workflow Contract

1. Parse YAML and assert the three required events exist.
2. Assert no `branches` or `branches-ignore` keys exist.
3. Assert no literal known repository branch names occur in workflow logic.
4. Assert exactly one build job feeds all test-group jobs for one target.
5. Assert test jobs download rather than build DuckDB.
6. Assert no HTTPFS source path is passed to CMake.
7. Assert no target ending in `_extension` or `_loadable_extension` is built.
8. Assert evidence uploads use unconditional execution.
9. Assert matrix values originate from manifest-normalization output.
10. Assert a feature-branch push is covered by the trigger definition.
