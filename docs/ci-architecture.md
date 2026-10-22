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

**Shared cloud account protection:** some batteries share mutable cloud
fixtures. The two independent workflows use the same GitHub Actions
`concurrency.group` with `cancel-in-progress: false` to avoid overlapping
runs for the same branch/ref. No execution order is guaranteed. After isolating
cloud accounts by platform this shared concurrency guard can be removed.

Linux uses the existing Bash/Python runtime. Windows uses the native MSVC
DuckDB/unittest binaries and Windows PowerShell/Python code; for some batteries
WSL remains an internal fixture host/legacy bridge. This change separates
GitHub Actions pipelines without migrating the legacy Windows runtime scripts.
Results continue to use the shared `qa/plan.py`, `qa/results.py` and
`scripts/aggregate-test-results.py` contracts.
