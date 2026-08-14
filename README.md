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

The Azure cloud profile runs the pinned `duckdb/duckdb-azure` cloud tests against an Irion-owned Azure Storage account. It does **not** use the DuckDB Labs containers or storage-account names from upstream CI.

Configure Azure under:

```text
Repository → Settings → Secrets and variables → Actions
```

### Repository secrets

Create or keep these **3** values under **Secrets → Repository secrets**:

| Secret | Value |
|---|---|
| `AZURE_TENANT_ID` | Microsoft Entra tenant ID containing the test Service Principal |
| `AZURE_CLIENT_ID` | Application/client ID of the test Service Principal |
| `AZURE_CLIENT_SECRET` | Client secret of the test Service Principal |

All three Azure identity values are intentionally read from the GitHub Actions `secrets` context.

### Repository variables

Create these **6** values under **Variables → Repository variables** exactly as shown:

| Variable | Value |
|---|---|
| `AZ_STORAGE_ACCOUNT` | `irionctstorageaccount` |
| `AZ_DATA_DIR` | `irionctstorageaccount-duckdb-tests-data/fixtures` |
| `AZ_TEMP_DIR` | `irionctstorageaccount-duckdb-tests-write/runs` |
| `ABFSS_STORAGE_ACCOUNT` | `irionctstorageaccount` |
| `ABFSS_DATA_DIR` | `irionctstorageaccount-duckdb-tests-data/fixtures` |
| `ABFSS_TEMP_DIR` | `irionctstorageaccount-duckdb-tests-write/runs` |

`AZ_DATA_DIR`, `AZ_TEMP_DIR`, `ABFSS_DATA_DIR` and `ABFSS_TEMP_DIR` use the format `container/path`; do not include `az://`, `azure://`, `abfs://`, `abfss://` or the storage-account hostname.

Both `AZ_TEMP_DIR` and `ABFSS_TEMP_DIR` are configured as stable roots. **Do not put a literal `<run-id>` in the GitHub variable.** The initializer automatically appends a unique execution suffix to both values:

```text
AZ_TEMP_DIR=irionctstorageaccount-duckdb-tests-write/runs/<GITHUB_RUN_ID>-<GITHUB_RUN_ATTEMPT>-<RUNNER_OS>
ABFSS_TEMP_DIR=irionctstorageaccount-duckdb-tests-write/runs/<GITHUB_RUN_ID>-<GITHUB_RUN_ATTEMPT>-<RUNNER_OS>
```

At runtime the repository also sets:

```text
AZURE_AUTH_ENV=1
AZURE_PROVIDER=cloud
AZURE_PROTOCOL=az
AZURE_STORAGE_ACCOUNT=${AZ_STORAGE_ACCOUNT}
DATA_DIR=${AZ_DATA_DIR}
TEMP_DIR=${AZ_TEMP_DIR}
```

This keeps Windows and Linux write tests isolated without adding per-run GitHub variables.

### ADLS Gen2 / ABFSS requirement

The account configured by `ABFSS_STORAGE_ACCOUNT` must have **Hierarchical Namespace (HNS)** enabled and expose a DFS endpoint. For the current test account this means:

```text
ABFSS_STORAGE_ACCOUNT=irionctstorageaccount
DFS endpoint=https://irionctstorageaccount.dfs.core.windows.net/
HNS enabled=true
```

The configured data and write containers are also the ADLS Gen2 filesystems used by the `abfs://` / `abfss://` upstream tests.

### Azure fixture bootstrap

Before the cloud tests start, `scripts/bootstrap-azure-test-data.py`:

1. authenticates Azure CLI with `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` and `AZURE_CLIENT_SECRET`;
2. creates the configured Blob/ADLS data and write containers if they do not already exist;
3. reads the `data/` directory from the exact pinned `duckdb/duckdb-azure` checkout;
4. uploads those fixtures under both the configured `AZ_DATA_DIR` and `ABFSS_DATA_DIR` targets, deduplicating the upload when they resolve to the same account/container/path;
5. leaves write-test objects isolated below the per-run `AZ_TEMP_DIR` and `ABFSS_TEMP_DIR` prefixes;
6. obtains a short-lived Azure Storage access token and exposes it only for the current workflow run;
7. sets the runtime `AZ_CLI_LOGGED_IN=1` marker after the Service Principal login.

`AZURE_ACCESS_TOKEN` and `AZ_CLI_LOGGED_IN` are **not** repository variables or secrets. They are generated at runtime so the pinned upstream `access_token_auth` and `cli_auth` scenarios can run without additional manual configuration.

With the values above, the containers/filesystems owned by this test environment are:

```text
irionctstorageaccount-duckdb-tests-data
irionctstorageaccount-duckdb-tests-write
```

The read fixture `data/l.parquet`, for example, is uploaded once and is addressable through both storage protocols:

```text
az://irionctstorageaccount-duckdb-tests-data/fixtures/l.parquet
abfss://irionctstorageaccount-duckdb-tests-data@irionctstorageaccount.dfs.core.windows.net/fixtures/l.parquet
```

Do **not** create or configure `duckdblabs-data` or `duckdblabs-write-testing`; those names belong to DuckDB Labs' own test infrastructure and are not part of this repository's Azure configuration.

The Service Principal must have Azure Blob data-plane permissions that allow reading the data filesystem and creating, reading, overwriting and deleting objects in the write filesystem. The current bootstrap also needs permission to create the containers/filesystems when they are missing.

The storage account network configuration must allow the GitHub Actions runner to reach the public storage endpoint, or the workflow must run on a runner inside an explicitly allowed network.

The upstream unauthenticated/public-container scenario remains optional. It requires public anonymous Blob access and is intentionally skipped when the storage account has public Blob access disabled.

## Test results

Each battery uploads a structured result artifact. The final aggregation reports, per profile:

- OK tests;
- KO tests;
- skipped/non-executed tests;
- missing external prerequisites;
- the final compatibility verdict.

Skipped/non-executed counts are informational only. They are deliberately not compared with hard-coded expected counts and do not make a passing battery fail. This allows pinned upstream suites to grow without manual baseline maintenance.

`config/extensions.yml` is the authoritative test-battery configuration file. See [`docs/results.md`](docs/results.md) for the aggregate-result semantics.
