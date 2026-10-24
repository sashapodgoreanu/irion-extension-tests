# DuckDB extension compatibility tests

This repository checks Irion's extensions and the DuckDB extensions they depend
on. The migration branch targets DuckDB `v2.0.0`. Extension test sources are
checked out from their upstream repositories at the revisions in
[`config/extensions.yml`](config/extensions.yml); upstream tests are not copied
into this repository.

## CI pipelines

GitHub Actions has two independent workflows:

- [Linux](.github/workflows/qa-linux.yml), on `ubuntu-24.04`;
- [Windows](.github/workflows/qa-windows.yml), on its configured Windows runner.

Each workflow resolves the shared configuration into its own platform matrix,
builds the configured DuckDB runtime in GitHub Actions, runs each selected
battery, and aggregates its results. The Linux and Windows workflows can be
started separately from the Actions page with a comma-separated `batteries`
filter; leave it empty to run every enabled battery.

The pipeline works in this order:

1. Validate the configuration and create a battery matrix for the platform.
2. Build DuckDB and `unittest` on the GitHub runner, or restore that runner's
   matching CI cache.
3. Check out each extension's upstream test repository at its configured pin.
4. Install and load the shared and battery-specific extensions through the
   DuckDB CLI. The runner checks `duckdb_extensions()` for install/load state
   and origin. The version lock ties upstream test pins to the DuckDB 2.0
   extension binaries; PostgreSQL Scanner and MSSQL also have runtime
   source-to-binary checks.
5. Start the battery's local services, run its SQLLogicTest profiles, and
   publish per-battery results for aggregation.

`config/runners.yml` controls matrix fail-fast behavior per platform. Linux sets
`failFast: false`, so one battery failure does not cancel the other Linux jobs;
the final aggregate still reports failed batteries. Windows keeps its configured
fail-fast setting, and its jobs are skipped for pull requests from
`aggiornamento_duckdb_2_0` so this migration PR verifies Linux only.

DuckDB builds belong to GitHub Actions. Do not run `scripts/build.sh` locally
for this test suite.

## Current Linux batteries

`config/extensions.yml` is the source of truth for enabled batteries, upstream
pins, profiles, extension requirements and service declarations.

| Battery | Test source and local dependencies |
| --- | --- |
| `httpfs` | HTTPFS SQL tests, Python HTTP server, Squid proxy and a local S3-compatible SeaweedFS service. The service type remains named `httpfs-minio` for configuration compatibility. |
| `ducklake` | DuckLake profiles for autoloading, SQLite and a local PostgreSQL 15 catalog. |
| `postgres_scanner` | PostgreSQL Scanner tests with a local PostgreSQL 17 service. |
| `delta` | Delta SQL tests and local fixtures. Two upstream tests requiring MinIO are explicitly excluded. |
| `azure` | Local Azurite and Squid profiles plus the upstream cloud profile against the configured Azure test account. |
| `unity_catalog` | Pinned upstream pytest suite; integration with this workflow's standard SQLLogicTest runner is outstanding. |
| `bigquery` | BigQuery v0.13.0 SQL tests against the configured GCP project and dataset. |
| `mssql` | MSSQL v0.3.0 tests with the upstream Docker SQL Server fixture and explicit trust for its self-signed test certificate. |
| `irion`, `irion_extension_security` | Repository-owned SQLLogicTests. |

The BigQuery battery uses the GCP project, dataset and service-account credentials
configured for GitHub Actions. Its extension also remains in `defaultExtensions`,
so it stays in the shared extension set except where a profile explicitly excludes
it. Its source/binary lock is retained in
[`config/extension-binary-pins.yml`](config/extension-binary-pins.yml). Iceberg
is disabled and has no battery-specific extension requirements.

## Configuration and documentation

- [`docs/ci-architecture.md`](docs/ci-architecture.md) describes workflow and
  job boundaries.
- [`docs/duckdb-2.0-migration.md`](docs/duckdb-2.0-migration.md) records the
  DuckDB 2.0 pins and migration findings.
- [`docs/services.md`](docs/services.md) describes local service contracts and
  cleanup.
- [`docs/test-profiles.md`](docs/test-profiles.md) describes profile selection
  and upstream test filters.
- [`docs/results.md`](docs/results.md) explains result artifacts and aggregate
  verdicts.
- [`test/README.md`](test/README.md) covers repository-owned SQLLogicTests.

All upstream pins and exclusions are reviewed in configuration and CI. A
passing Linux GitHub Actions run is the compatibility result for this branch.
