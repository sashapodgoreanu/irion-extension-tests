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

## Test results

Each battery uploads a structured result artifact. The final aggregation reports, per profile:

- OK tests;
- KO tests;
- skipped/non-executed tests;
- missing external prerequisites;
- the final compatibility verdict.

Skipped/non-executed counts are informational only. They are deliberately not compared with hard-coded expected counts and do not make a passing battery fail. This allows pinned upstream suites to grow without manual baseline maintenance.

`config/extensions.yml` is the authoritative test-battery configuration file. See [`docs/results.md`](docs/results.md) for the aggregate-result semantics.
