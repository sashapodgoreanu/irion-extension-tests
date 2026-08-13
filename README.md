# Irion DuckDB Extension Compatibility Tests

This repository verifies that the DuckDB extensions used by Irion remain compatible with the selected DuckDB release.

The GitHub Actions workflow builds one DuckDB runtime and runs the enabled Irion and upstream extension test batteries against it.

## Running the tests

The workflow runs automatically on:

- pushes;
- pull requests;
- manual execution through `workflow_dispatch`.

The main configuration file is:

```text
config/extensions.yml
```

Use this file to configure:

- the DuckDB and `extension-ci-tools` versions;
- the runtime platform;
- default extensions loaded by every battery;
- enabled test batteries;
- upstream repositories and immutable pins;
- test profiles, services and ignored tests.

Configuration errors stop the workflow before the DuckDB build starts.

## Irion tests

Repository-owned tests belong under:

```text
test/sql/irion/
```

To add a new Irion scenario:

1. Create a `.test` file under `test/sql/irion/`.
2. Add reusable initialization SQL under `test/scripts/irion/` when needed.
3. Update `test/configs/irion.json` when the scenario needs initialization or test-specific settings.

No numeric test-count baseline needs to be updated when the suite grows. New tests are discovered by the configured test paths/globs.

Current layout:

```text
test/
├── configs/irion.json
├── scripts/irion/initialize.sql
└── sql/irion/*.test
```

See [`test/README.md`](test/README.md) for the SQLLogicTest-specific details.

## Extension tests

Upstream extension tests are not copied into this repository. Each battery checks out the repository and immutable pin declared in `config/extensions.yml`.

A battery is configured under `testBatteries`:

```yaml
testBatteries:
  example:
    isEnabled: true
    runner: standard
    source: remote
    repository: owner/repository
    pin: exact-commit-or-release-tag
    submodules: recursive
    services: []
    prerequisites: []
    profiles:
      - name: all
        tests: test/sql/*
        services: []
    extensions:
      - name: example
        isUsed: true
    ignoredTests: []
```

Important fields:

| Field | Purpose |
|---|---|
| `isEnabled` | Enables or disables the battery job. |
| `repository` | Upstream repository in `owner/name` format. |
| `pin` | Exact commit SHA or published release tag. |
| `profiles[].tests` | SQLLogicTest path or glob to execute. |
| `extensions` | Extensions required by this battery. |
| `services` | Local services required by the tests. |
| `ignoredTests` | Explicit exclusions with a mandatory reason. |

Changing `isEnabled` does not add or remove an extension from `defaultExtensions`. Changing `defaultExtensions` does not enable or disable a test battery.

## BigQuery test configuration

The BigQuery battery uses these Google Cloud resources:

```text
Project ID: duckdb-bigquery
Dataset ID: duckdb_bigquery_tests
Dataset location: EU
Cloud Storage bucket: ctstorage-bucket
```

Create the dataset once, if it does not already exist:

```powershell
bq --location=EU mk --dataset duckdb-bigquery:duckdb_bigquery_tests
```

Configure these values in:

```text
Repository → Settings → Secrets and variables → Actions
```

| Name | Value | Sensitive |
|---|---|---|
| `GCS_SERVICE_ACCOUNT_KEY` | Complete service-account JSON file content | Yes |
| `BQ_TEST_PROJECT` | `duckdb-bigquery` | No |
| `BQ_TEST_DATASET` | `duckdb_bigquery_tests` | No |
| `BQ_TEST_BILLING_PROJECT` | `duckdb-bigquery` | No |
| `BQ_TEST_EXPORT_URI` | `gs://ctstorage-bucket/duckdb-bigquery-tests/export-*.parquet` | No |

Only `GCS_SERVICE_ACCOUNT_KEY` contains confidential credentials. The other values are configuration values. They can still be stored as repository secrets because the workflow reads them through the GitHub Actions `secrets` context.

`BQ_TEST_EXPORT_URI` enables the upstream `bigquery_extract` test. The service account must have `roles/storage.objectAdmin` on `ctstorage-bucket` so the test can create and remove exported Parquet objects.

The service account must also be able to:

- run BigQuery jobs;
- read the public datasets used by the upstream suite;
- create, update and delete tables in `duckdb_bigquery_tests`.

Verify the configured resources from the command line with:

```powershell
bq show duckdb-bigquery:duckdb_bigquery_tests
gcloud storage ls gs://ctstorage-bucket
```

Do not commit the service-account JSON file to this repository.

## Azure cloud test configuration

The pinned `duckdb/duckdb-azure` upstream suite contains real Azure Storage tests under `test/sql/cloud/`. The upstream cloud bootstrap authenticates with an Azure Service Principal.

The external credentials that must be supplied to the test environment are:

| Environment variable | Purpose | Sensitive |
|---|---|---|
| `AZURE_TENANT_ID` | Microsoft Entra tenant containing the test Service Principal | No |
| `AZURE_CLIENT_ID` | Application/client ID of the test Service Principal | No |
| `AZURE_CLIENT_SECRET` | Client secret used by the Service Principal | Yes |

For GitHub Actions, configure these values under:

```text
Repository → Settings → Secrets and variables → Actions
```

`AZURE_CLIENT_SECRET` must be stored as a repository secret. `AZURE_TENANT_ID` and `AZURE_CLIENT_ID` are identifiers rather than passwords, but they may also be stored as secrets if the workflow uses the `secrets` context for all three values. The workflow that enables the cloud profile must expose them to the test process with the same environment-variable names.

The pinned upstream `scripts/env_azure` bootstrap derives the remaining cloud-test environment. These values should normally be created by the test bootstrap rather than maintained as credentials in GitHub:

| Environment variable | Upstream value / purpose |
|---|---|
| `AZURE_AUTH_ENV` | `1`; enables the environment-authenticated cloud test contract |
| `AZURE_PROVIDER` | `cloud` |
| `AZ_STORAGE_ACCOUNT` | `duckdblabstestdatablob`; Azure Blob Storage account used by `az://` tests |
| `AZ_DATA_DIR` | `duckdblabs-data/common/azure_data`; read-only fixture path |
| `AZ_TEMP_DIR` | `duckdblabs-write-testing/extension/azure/<unique-suffix>`; isolated write-test path |
| `ABFSS_STORAGE_ACCOUNT` | `duckdblabstestdata`; ADLS Gen2 account used by `abfs://`/`abfss://` tests |
| `ABFSS_DATA_DIR` | `duckdblabs-data/common/azure_data`; ADLS fixture path |
| `ABFSS_TEMP_DIR` | `duckdblabs-write-testing/extension/azure/<unique-suffix>`; isolated ADLS write-test path |

The unique temporary suffix is generated for each test execution to reduce collisions. The Windows and Linux test batteries are intentionally serialized because both operating systems use the same external cloud accounts and shared fixture roots.

The Service Principal must be able to read the fixture data and must have sufficient Blob/ADLS permissions to create, read, overwrite and delete objects in the write-testing location. ADLS Gen2 tests may additionally require filesystem ACLs appropriate to the Service Principal.

Some upstream Azure tests have additional, test-specific environment gates. They are not primary repository credentials:

| Environment variable | Used for |
|---|---|
| `AZURE_ACCESS_TOKEN` | `access_token_auth.test`; generated at runtime, normally with Azure CLI |
| `AZ_CLI_LOGGED_IN` | `cli_auth.test`; marker used only after a successful `az login` |
| `DUCKDB_AZURE_PUBLIC_CONTAINER_AVAILABLE` | Enables the unauthenticated/public-container test |
| `PUBLIC_AZ_STORAGE_ACCOUNT` | Public account used by that test; upstream uses `duckdbtesting` |
| `ENABLE_DATA_INTEGRITY` | Enables the separate persistent test-data integrity check |
| `DUCKDB_AZURE_PERSISTENT_SECRET_AVAILABLE` | Indicates that the persistent Azure secret required by the integrity check was created |

Do not store `AZURE_ACCESS_TOKEN` as a long-lived repository secret. It is short-lived and should be generated during the job when that authentication scenario is tested.

**Current repository status:** the Azure battery in `config/extensions.yml` currently executes the local `azurite` and `proxy` profiles only. `test/sql/cloud/*` is not yet part of the configured Azure battery. Adding the three Service Principal credentials alone therefore does not enable cloud execution; a dedicated cloud profile/bootstrap must also be added to the battery configuration.

## Test results

Each battery uploads a structured result artifact. The final aggregation reports, per profile:

- OK tests;
- KO tests;
- skipped/non-executed tests;
- missing external prerequisites;
- the final compatibility verdict.

Skipped/non-executed counts are informational only. They are deliberately not compared with hard-coded expected counts and do not make a passing battery fail. This allows pinned upstream suites to grow without manual baseline maintenance.

`config/extensions.yml` is the authoritative test-battery configuration file. See [`docs/results.md`](docs/results.md) for the aggregate-result semantics.
