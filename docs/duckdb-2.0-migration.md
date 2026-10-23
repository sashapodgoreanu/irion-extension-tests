# DuckDB 2.0.0 LTS migration

Target branch: `aggiornamento_duckdb_2_0` (created from `main`).
Target DuckDB and CI tools version: `v2.0.0`.
Selection date: 2026-10-23.

| Battery | Upstream repository | Pinned reference | Selection |
| --- | --- | --- | --- |
| httpfs | duckdb/duckdb-httpfs | `77392a72077a85897db2519fae11e2c0da972b8a` | DuckDB 2.0 release-ready `main` |
| ducklake | duckdb/ducklake | `f67b3648787f6ede9ad6a26dbbaa9f8cc72b84cf` | Latest `main`, independently versioned |
| postgres_scanner | duckdb/duckdb-postgres | `e53270e1afdd45d6e4d6b41375ec54f5e17c1fae` | Submodules updated for DuckDB 2.0 |
| delta | duckdb/duckdb-delta | `8a12490ad047fcc626dae3c47fc21c9f9fd9d540` | Submodules updated for DuckDB 2.0 |
| iceberg | duckdb/duckdb-iceberg | `b0ef95eda41c44734b2d229659190b18a5716eab` | Latest DuckDB 2.0 `main` |
| azure | duckdb/duckdb-azure | `2ea75dda3f86ebb05d07261b29074492090e1be3` | Explicit upstream DuckDB 2.0 bump |
| unity_catalog | duckdb/unity_catalog | `d8035e4fed353bce957a047a36179344a9c3edf1` | Explicit upstream DuckDB 2.0 bump |
| bigquery | hafenkran/duckdb-bigquery | `5439a6a58439af4c05064f80a28b159c5a1424e7` | v0.13.0 release commit (DuckDB 2.0) |
| mssql | hugr-lab/mssql-extension | `v0.3.0` | First DuckDB 2.0 release, commit `bfd347ffa89dc520eb0fb82c857b3c7af12673dc` |
| irion / irion_extension_security | Local repository | `self` | No external upstream pin |

## Known migration considerations

- DuckDB 2.0 defaults to the extensible PEG SQL parser and requires C++17.
- BigQuery v0.13.0 changes SQLLogicTest environment variable placeholders to
  `{BQ_TEST_BILLING_PROJECT}` and fixes the older REST NULL-array error test.
  The new upstream tests should remain active.
- Azure 2.0 expects four HEAD requests rather than three in its private HTTP
  statistics assertion. Only the variable cache-sensitive GET statistic is adapted.
- Delta remains local-only, with MinIO tests explicitly excluded.
- MSSQL v0.3.0's upstream tests and previous excluded cases require CI revalidation.
- Windows is disabled in `config/runners.yml` on `main`; it remains disabled
  in this branch until the new Linux baseline is verified.
- DuckDB 2.0 may create database files older DuckDB releases cannot read.
  Use isolated CI fixtures and shadow systems, not shared 1.x databases.

These pins identify upstream source, not proof of compatibility between installed
binary extensions and every new upstream test. Only a passing CI run confirms
the selected battery combination.

References:
- https://duckdb.org/2026/10/21/announcing-duckdb-200
- https://duckdblabs.github.io/extension-release-status/v2.0.0/
- https://github.com/hafenkran/duckdb-bigquery/releases/tag/v0.13.0
- https://github.com/hugr-lab/mssql-extension/releases/tag/v0.3.0
