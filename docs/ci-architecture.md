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

**External cloud fixtures:** some Linux and Windows batteries share mutable
cloud accounts. Concurrent platform runs may interfere with each other's
fixtures until these resources are isolated by OS. This is a test-fixture
limitation, not a CI dependency.

Linux uses the existing Bash/Python runtime. Windows uses the native MSVC
DuckDB/unittest binaries and Windows PowerShell/Python code; for some batteries
WSL remains an internal fixture host/legacy bridge. This change separates
GitHub Actions pipelines without migrating the legacy Windows runtime scripts.
Results continue to use the shared `qa/plan.py`, `qa/results.py` and
`scripts/aggregate-test-results.py` contracts.
