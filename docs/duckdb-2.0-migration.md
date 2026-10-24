# DuckDB 2.0.0 LTS migration

Target branch: `aggiornamento_duckdb_2_0` (created from `main`).
Target DuckDB version: `v2.0.0`.
`extension-ci-tools` is pinned at SHA `969bc76276acec1c0a3922ff500d2ec3a1a3b037` because it does **not** provide a `v2.0.0` git tag.
Selection date: 2026-10-23. Linux CI is the migration target; all DuckDB builds
run in GitHub Actions.

| Battery | Upstream repository | Pinned reference | Selection |
| --- | --- | --- | --- |
| httpfs | duckdb/duckdb-httpfs | `77392a72077a85897db2519fae11e2c0da972b8a` | DuckDB 2.0 release-ready `main` |
| ducklake | duckdb/ducklake | `417a9117f590e8141742ac0579d02f6a90162e37` | Exact DuckDB 2.0 distributed binary revision (`417a9117f5`) |
| postgres_scanner | duckdb/duckdb-postgres | `c0f5a3c0c4b68b02afbf669d36d7f0e503985c88` | Exact upstream revision reported by the DuckDB 2.0.0 distributed extension (`c0f5a3c0c4`) |
| delta | duckdb/duckdb-delta | `9dcfb65b99fcafaa068222c2490abc143da4cc8e` | Exact DuckDB 2.0 distributed binary revision (`9dcfb65b99`) |
| iceberg | duckdb/duckdb-iceberg | `b0ef95eda41c44734b2d229659190b18a5716eab` | Latest DuckDB 2.0 `main` |
| azure | duckdb/duckdb-azure | `906e92458c33309e5d9413e14a85aad7b4d2275f` | Exact DuckDB 2.0 distributed binary revision (`906e92458c`) |
| unity_catalog | duckdb/unity_catalog | `cc59382f5292997293a57c2ab336c9aa97c05f2d` | Exact DuckDB 2.0 distributed binary revision (`cc59382f52`) |
| bigquery | hafenkran/duckdb-bigquery | `5439a6a58439af4c05064f80a28b159c5a1424e7` | v0.13.0 release commit (DuckDB 2.0) |
| mssql | hugr-lab/mssql-extension | `v0.3.0` | First DuckDB 2.0 release, commit `bfd347ffa89dc520eb0fb82c857b3c7af12673dc` |
| irion / irion_extension_security | Local repository | `self` | No external upstream pin |

## PostgreSQL scanner pin and release alignment

The DuckDB 2.0.0 repository binary reports extension version `c0f5a3c0c4`,
corresponding to the full upstream commit `c0f5a3c0c4b68b02afbf669d36d7f0e503985c88`.
Our previous pin `e53270e1afdd45d6e4d6b41375ec54f5e17c1fae` was four commits newer than
the distributed binary. The intervening commits add PostgreSQL insertion/default
column support and newer SQLLogicTests that cannot be assumed to work against
the existing binary. We use the exact matching source commit and retain the
fail-closed source/binary version check in `scripts/run-postgres-scanner-tests.sh`.
Recheck the distribution's version before advancing this pin again.

## All active extension test pins follow the binaries

The pinned sources are the revisions identified by `duckdb_extensions()` after
installing extensions with the DuckDB v2.0.0 CI runtime, **not** the latest upstream
`main`. For source commit revisions, the pinned full SHA must start with the
binary's reported shortened SHA; for tagged releases, the installed semantic version must match the verified
source tag, and the pin must equal that tag or its immutable commit.

The reproducible versions are recorded in `config/extension-binary-pins.yml` and
enforced by `tests/config/test_extension_binary_pins.py`.
Iceberg remains disabled and is intentionally outside the active binary contract
until explicitly re-enabled. Never weaken a mismatched runtime gate to make CI green.

## Known migration considerations

- DuckDB 2.0 defaults to the extensible PEG SQL parser and requires C++17.
- BigQuery v0.13.0 changes SQLLogicTest environment variable placeholders to
  `{BQ_TEST_BILLING_PROJECT}` and fixes the older REST NULL-array error test.
  The BigQuery battery remains active against the configured GCP project, dataset
  and service account; its source/binary lock is retained with the shared default.
- Both Azure matrices include Azurite and Squid profiles plus the upstream cloud
  profile. The cloud profile uses the configured Azure test account and its workflow
  bootstrap, so the fixtures are mutable shared resources across Linux and Windows.
- Azure 2.0 expects four HEAD requests rather than three in its private HTTP
  statistics assertion. Only the variable cache-sensitive GET statistic is adapted.
- Delta remains local-only, with MinIO tests explicitly excluded.
- Iceberg is disabled indefinitely: both `testBatteries.iceberg.isEnabled` and the `defaultExtensions` Iceberg `isUsed` flag are `false`. Its dedicated extensions are an empty list, so the Avro/HTTPFS/TPCH dependencies formerly declared for Iceberg are not installed by this battery. There are no Iceberg services or prerequisites. Reactivation requires explicitly restoring this configuration; the upstream reference and fixture files remain dormant.
- MSSQL v0.3.0 tests TLS against a local SQL Server with a self-signed
  certificate. The configured test connections explicitly trust that fixture
  certificate in both the runner and service-manager defaults, while preserving
  caller-provided connection values and DuckDB's signed-extension verification.
- DuckDB 2.0 CLI autoinstalls use the build-local extension repository. Runtime
  artifacts must carry that repository back to the same build path in test jobs;
  HTTPFS fixture generation also needs the built `tpch` extension for `DBGEN`.
  Its standard runner reuses that fixture-installed TPCH binary instead of
  reinstalling it from a different extension repository.
- DuckLake's SQLite and PostgreSQL profiles must leave JSON unloaded for the
  upstream `add_files_json_without_extension.test`. The JSON extension remains
  installed so tests that require it can still load it on demand.
- The pinned Azure fixture uploader defaults to Azurite ports 28000–28002, while
  this QA service assigns ports from its service manifest. The service manager
  adapts a temporary uploader copy to the configured endpoints so each profile
  loads its fixtures into its own emulator.
- At the binary-matching Unity Catalog pin, upstream replaced its SQLLogicTest
  suite with pytest tests using the `duckdb-pytest-driver`. The QA workflow runs
  the pinned `oss_local` suite with the upstream OSS container image and test
  binary. It stages the installed extension binaries in the build layout that
  the pytest driver resolves, while retaining the local extension repository
  for DuckDB 2.0 installs. Its old Java service and ignored paths have been
  removed because the pinned pytest fixtures own those resources.
- The current DuckLake binary run also reports that
  `add_files_type_check_variant.test` unexpectedly succeeds when a STRUCT Parquet
  file is added to a VARIANT table with `allow_missing => true`. This remains an
  open compatibility failure; the test has not been suppressed.
- HTTPFS at the selected commit has moved its S3 test service to SeaweedFS. Its
  fixture is `scripts/seaweedfs_s3.yml` plus `seaweedfs_s3_config.json`; the old
  `scripts/minio_s3.yml` no longer exists at this pin. The service manager now
  starts and cleans up that pinned upstream fixture, and checks the completion
  marker from its one-shot `s3_setup` container. The compose setup still uses
  the MinIO Client `mc` as an S3 client, but does not run a MinIO server.
- Linux and Windows have separate workflows and explicitly select their own
  platform. This migration task targets Linux; a Windows workflow result is
  separate and does not establish the Linux baseline.
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
