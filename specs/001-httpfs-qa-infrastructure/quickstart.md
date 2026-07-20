# Quickstart: HTTPFS QA Infrastructure

**Feature**: `001-httpfs-qa-infrastructure`

This guide describes the expected maintainer workflow after the feature is implemented.

## 1. Run from any branch

The workflow is designed to run for any branch containing `.github/workflows/extension-qa.yml`.

### Push invocation

```bash
git switch <your-branch>
git push origin <your-branch>
```

The `push` trigger has no branch filter, so the run is eligible regardless of the branch name.

### Pull-request invocation

Open or update a pull request. The unfiltered `pull_request` trigger runs the same validation, shared DuckDB build, and test-group matrix.

### Manual invocation

After the workflow exists on the repository's default branch:

1. Open **Actions**.
2. Select **DuckDB Extension QA**.
3. Select **Run workflow**.
4. Choose the branch or tag to test.
5. Start the run.

Manual dispatch selection depends on the workflow existing on the default branch; feature development is validated through normal branch pushes and pull requests before merge.

## 2. Expected job flow

For the initial HTTPFS feature, the workflow should display:

```text
validate-manifest
        │
        ├── build matrix
        └── HTTPFS test-group matrix
                    │
                    ▼
build-duckdb
        │
        └── shared DuckDB artifact
                    │
                    ▼
test-group (httpfs-standard)
```

There must be only one DuckDB build job for the initial Linux/Release target.

## 3. What the build job is allowed to produce

Expected artifact content:

```text
bin/duckdb
bin/unittest
metadata/build.json
checksums/SHA256SUMS
runtime-libs/          # only when required
```

The artifact must not contain:

```text
httpfs.duckdb_extension
*.duckdb_extension built by this repository
HTTPFS object files
HTTPFS static libraries
HTTPFS source checkout
```

The build log should show only the standard DuckDB build and the `duckdb`/`unittest` targets requested by this repository.

## 4. What the HTTPFS test group does

The HTTPFS matrix job:

1. downloads the shared DuckDB artifact;
2. checks out `duckdb/duckdb-httpfs` at commit `c3f215ab360f04dc3d3d5305fa81849c0121f111`;
3. creates isolated runtime directories;
4. starts the Python HTTP server, Squid, and MinIO/S3-compatible test services;
5. waits for every readiness check;
6. runs `INSTALL httpfs; LOAD httpfs;` using the official prebuilt extension repository;
7. verifies installation source and loaded state through `duckdb_extensions()`;
8. discovers selected upstream tests;
9. executes them through the shared `unittest` binary and `--test-dir`;
10. tears down services and uploads evidence even when a phase fails.

Conceptual runner invocation:

```bash
bin/unittest \
  --test-config generated/httpfs-standard.json \
  --test-dir upstream/httpfs \
  "<manifest-selected HTTPFS tests>"
```

## 5. Inspect the evidence

### Workflow summary

The job summary should include:

- DuckDB ref and resolved commit;
- `extension-ci-tools` ref and resolved commit;
- normalized manifest digest;
- enabled extension list;
- HTTPFS test repository and commit;
- service readiness status;
- installed HTTPFS version/source;
- discovered, selected, excluded, executed, passed, and failed counts;
- final result classification.

### Build artifact

Download the shared DuckDB artifact and verify:

```bash
sha256sum -c checksums/SHA256SUMS
./bin/duckdb --version
./bin/unittest --list-tests "*" >/dev/null
find . -name '*.duckdb_extension' -print
```

The final `find` command must return no locally built extension binary.

### Test-group artifact

Expected files include:

```text
result.json
summary.md
extensions.json
tests.discovered.txt
tests.selected.txt
tests.excluded.json
generated-test-config.json
unittest.log
services/
cleanup.log
```

## 6. Interpret failures

| Classification | First place to inspect |
|---|---|
| `CONFIGURATION_FAILED` | manifest/schema validation logs |
| `DUCKDB_BUILD_FAILED` | configure/build logs |
| `ARTIFACT_FAILED` | checksums, `ldd`, relocation smoke-test logs |
| `INFRASTRUCTURE_FAILED` | `services/` readiness and native logs |
| `EXTENSION_INSTALL_FAILED` | installation log and isolated extension directory |
| `EXTENSION_LOAD_FAILED` | `extensions.json` and generated load statements |
| `EMPTY_DISCOVERY` | discovered/selected inventories and include/exclude rules |
| `FUNCTIONAL_FAILED` | `unittest.log` and failing upstream test paths |
| `TIMED_OUT` | result JSON, process tree, and service/test logs |
| `CRASHED` | exit signal, core-dump metadata, and test output tail |
| `CLEANUP_FAILED` | cleanup log and resource inventory |

## 7. Validate configuration locally

The implementation will expose commands equivalent to:

```bash
python -m scripts.qa.validate_manifest \
  --manifest config/extensions.yml \
  --schema config/schema/extensions.schema.json

python -m scripts.qa.render_matrix \
  --manifest config/extensions.yml \
  --output-dir build/generated
```

Unit and contract tests:

```bash
python -m unittest discover -s tests/unit -p 'test_*.py'
python -m unittest discover -s tests/contract -p 'test_*.py'
```

The workflow-trigger contract test must fail when a `branches` or `branches-ignore` key is introduced.

## 8. Add a future extension

After this feature is implemented, adding an extension should require:

1. add an enabled entry to `config/extensions.yml`;
2. declare its prebuilt install/load statements;
3. pin its upstream test repository and full commit SHA;
4. define one or more test groups;
5. reference `adapter: none` or add an adapter implementation;
6. run validation;
7. push any branch;
8. confirm the new group appears in the generated matrix;
9. confirm every group now installs and loads the expanded enabled extension set.

The DuckDB build job must remain unchanged.

## 9. HTTPFS-specific maintenance

When changing DuckDB version:

1. update the DuckDB and CI-tools refs in the manifest;
2. determine the HTTPFS commit declared by that DuckDB release;
3. update the pinned HTTPFS test-source commit;
4. review upstream integration scripts and service-image changes;
5. review all exclusions;
6. run the workflow from the upgrade branch;
7. compare test inventory and results with the previous DuckDB target.

Never respond to a missing HTTPFS binary by adding HTTPFS source to the build. The run must fail clearly until a compatible approved prebuilt binary source is available.
