# CI architecture

Linux and Windows now use **two standalone GitHub Actions workflows**:

| Workflow | Triggers | Jobs |
| --- | --- | --- |
| `.github/workflows/qa-linux.yml` | pull_request and manual dispatch | Linux matrix → build → tests → aggregate |
| `.github/workflows/qa-windows.yml` | pull_request and manual dispatch | Windows matrix → build → tests → aggregate |

There is **no central orchestrator, no workflow_call, no cross-OS job dependency**.
Each Actions run has its own configuration, build, tests, artifacts and verdict.
Both read the same pinned DuckDB versions and batteries from
`config/extensions.yml` and runner definitions from `config/runners.yml`
through `scripts/prepare-runner-matrices.py`. No pins are duplicated.

Each workflow passes `--platforms linux` or `--platforms windows` explicitly;
this overrides disabled runner defaults, so Windows is not disabled by the
previous `config/runners.yml` setting. Both independently run on pull requests
and expose a manual `batteries` CSV filter (empty = all enabled batteries).

**Independent scheduling:** each workflow uses its own GitHub Actions
`concurrency.group` keyed by `github.workflow` and `github.ref`.
There is no common queue or imposed Linux/Windows order: both pipelines can
run at the same time, or either can run alone. Multiple runs of the same
workflow on the same ref remain serialized.

**External cloud fixtures:** Azure and BigQuery use the accounts and credentials
configured for these workflows. Their tests can create or modify cloud fixtures;
concurrent Linux and Windows runs may affect the same resources. BigQuery is also
installed as a shared extension in batteries that include it.

Linux uses the existing Bash/Python runtime. Windows uses the native MSVC
DuckDB/unittest binaries and Windows PowerShell/Python code; for some batteries
WSL remains an internal fixture host/legacy bridge. This change separates
GitHub Actions pipelines without migrating the legacy Windows runtime scripts.
Results continue to use the shared `qa/plan.py`, `qa/results.py` and
`scripts/aggregate-test-results.py` contracts.

## Runner map and maintenance findings

The main execution path is:

1. `scripts/prepare-runner-matrices.py` resolves battery configuration into
   platform-specific profiles and service manifests.
2. The workflow checks out each remote test repository at `matrix.pin` and
   downloads the DuckDB runtime artifact built or restored by the build job.
3. `scripts/run-test-battery.sh` prepares a battery, checks prerequisites,
   starts battery services and finalizes its result.
4. Standard SQLLogicTest batteries use `scripts/run-standard-tests.sh`; the
   PostgreSQL Scanner and MSSQL batteries use specialized runners that also
   validate source-to-binary versions. Unity Catalog uses its pinned upstream
   `duckdb-pytest-driver` suite and the suite-owned OSS container.
5. `scripts/service-manager.sh` owns local service startup, environment setup,
   readiness checks, log capture and cleanup.

The runner configuration exposes `failFast` per platform and passes that value
to the matrix strategy. Linux enables matrix cancellation, so the first failed
battery stops the remaining Linux jobs. Windows retains its configured
fail-fast setting and skips jobs for pull requests from
`aggiornamento_duckdb_2_0`, allowing that migration PR to validate Linux only.

`config/extensions.yml` and `config/extension-binary-pins.yml` carry the battery
and binary contracts. `tests/config` checks the compiled matrices, service inputs,
source pins and fail-closed version gates before a runtime build begins.

Two maintenance pressure points surfaced during the DuckDB 2.0 migration:

- `service-manager.sh` combines dispatch and lifecycle code for several
  services. The HTTPFS migration exposed the risk of a familiar contract name
  hiding a changed upstream implementation: `httpfs-minio` now starts
  SeaweedFS. The adapter validates the pinned fixture files and delegates
  cleanup to the pinned upstream script. Future service growth should preserve
  this lifecycle contract and keep each adapter's startup and cleanup easy to
  inspect.
- `prepare-runner-matrices.py` adds the Azure cloud profile as an overlay and
  moves Azurite into the local profiles. Matrix tests check both platforms use
  the same profiles. Changes to this overlay must update the Azure environment
  initializer, fixture bootstrap and matrix assertions together.

The PostgreSQL Scanner and MSSQL source/binary gates are intentional safety
checks. Advancing a test pin without updating its observed DuckDB binary version
must stop configuration or runtime validation.

The Unity Catalog pytest runner stages the downloaded `unittest` binary and
extensions under the pinned checkout's `build/release` layout, then runs the
upstream command `uv run pytest -n0 -s` with `LD_LIBRARY_PATH` pointing at that
build's `src` directory. This preserves the upstream driver's default local
suite selection (OSS, functions, and IRC; Databricks is deselected by default).
The Docker capability is derived from the runner kind because the upstream
fixture owns container lifecycle instead of declaring a QA-managed service.
