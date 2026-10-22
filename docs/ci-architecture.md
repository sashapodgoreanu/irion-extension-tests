# CI architecture

This repository tests a common set of pinned DuckDB extensions on Linux and
Windows. Test batteries, upstream repositories, pins, profiles, and expected
extensions are defined only in `config/extensions.yml`. Platform defaults
are defined in `config/runners.yml`.

## GitHub Actions pipelines

| File | Responsibility |
| --- | --- |
| `.github/workflows/extension-qa.yml` | Single pull-request/manual entry point; validates configuration, resolves matrices, uploads the execution plan and invokes platform workflows |
| `.github/workflows/qa-windows.yml` | Reusable Windows pipeline: MSVC build, Windows test matrix, artifacts and Windows-only aggregation |
| `.github/workflows/qa-linux.yml` | Reusable Linux pipeline: Linux build, Linux test matrix, artifacts and Linux-only aggregation |

The two reusable workflows accept the same six `workflow_call` inputs:
`matrix`, `duckdb_version`, `ci_tools_version`, `operating_system`,
`architecture`, and `github_runner`. These are derived centrally from
`scripts/prepare-runner-matrices.py`; the child workflows do not own copies
of the pinned source configuration. The caller passes credentials with
`secrets: inherit`.

## Failure and resource isolation

Windows runs before Linux because some batteries share external cloud accounts
and resources. Linux still runs if Windows fails, and reports an independent
verdict; a failure in either selected platform fails the complete run.
Selecting only one platform invokes only its pipeline.

Each platform builds its own native DuckDB runtime and uses distinct result,
log and summary artifacts. Existing artifact naming and result schemas are
preserved.

## Running specific batteries

Manual `workflow_dispatch` inputs are:

- `batteries`: comma-separated battery names; empty means all enabled batteries.
- `platforms`: `linux`, `windows`, `linux,windows`; empty uses
  `config/runners.yml` (currently Linux enabled and Windows disabled).

Pull requests from `feature/irion-extension-security-filters` deliberately
select both platforms and every enabled battery, as before.

## Runner implementation

This workflow split does **not** migrate Windows test adapters. The Windows
runner still invokes native `duckdb.exe`/`unittest.exe` for the supported
batteries and WSL-assisted orchestration for the remaining batteries.
The Linux runner retains its existing Bash/Python implementation. Windows-native
migration can be made separately without changing the shared test matrix.

Results are generated and validated by the existing `qa/plan.py`,
`qa/results.py`, `scripts/write-test-result.py` and
`scripts/aggregate-test-results.py` contracts.
