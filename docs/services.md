# Composable QA services

Configuration schema v4 replaces the single battery `setup` value and profile
`runtimeSetup` value with ordered service lists. Services are compiled into the
execution plan and started by `scripts/service-manager.sh`.

## Battery services

Battery services live for the whole battery execution:

```yaml
services:
  - name: http-server
    type: python-http
    port: 8008
  - name: proxy
    type: squid
    port: 3128
  - name: object-store
    type: httpfs-minio
```

They are started before the selected runner and stopped in reverse order even when
setup or test execution fails.

Azure uses the upstream-supported local Azurite environment instead of silently
skipping all tests when a real Azure account is absent:

```yaml
services:
  - name: storage-emulator
    type: azurite
    port: 10000
```

The Azurite service starts the local emulator, publishes the development-storage
connection variables and runs the pinned upstream fixture upload script before the
SQLLogicTest profile begins.

## Profile services

A standard-runner profile can declare services that exist only while that profile is
running:

```yaml
profiles:
  - name: postgres
    tests: test/sql/*
    services:
      - name: postgres-catalog
        type: postgres
        version: "15"
        database: ducklakedb
        username: postgres
        port: 5432
```

Profile service names cannot duplicate battery service names. Specialized runners
cannot declare profile-scoped services because their profile execution is not generic.

## Prerequisites

External authentication is modeled separately from local services:

```yaml
prerequisites:
  - type: google-bigquery
```

The compiler derives workflow capabilities from services and prerequisites. GitHub
Actions installs dependencies and authenticates from those capabilities rather than
from battery names.

## Supported service types

- `python-http`
- `squid`
- `httpfs-minio`
- `azurite`
- `postgres`
- `sqlserver`

The service manager owns health checks, environment variables, log collection and
cleanup. Existing HTTPFS, Azure, PostgreSQL and SQL Server behavior remains pinned to
the configured upstream repositories and versions.

## Runtime artifacts

Each matrix case generates:

```text
services.json
prerequisites.json
capabilities.json
profile-services-<profile>.json
```

These files are copied into the test logs so the exact service contract used by a run
is inspectable.
