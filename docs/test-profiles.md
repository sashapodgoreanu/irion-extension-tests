# Declarative test profiles

A test battery describes source ownership, the runner and shared extensions. Its
`profiles` collection describes the ordered SQLLogicTest executions performed by
that battery.

```yaml
profiles:
  - name: sql
    tests: test/sql/*
    testConfig:
      kind: generated
      excludedExtensions: []
      staticallyLoadedExtensions:
        - core_functions
        - parquet
```

## Generated configurations

`kind: generated` creates a SQLLogicTest configuration from the resolved extension
set. `excludedExtensions` controls which extensions are intentionally not loaded
for that profile. This is used for lifecycle and autoloading tests without adding
battery-name conditions to the runner.

```yaml
- name: autoload
  tests: test/extension/*
  testConfig:
    kind: generated
    excludedExtensions:
      - httpfs
    staticallyLoadedExtensions:
      - core_functions
```

## Upstream configurations

`kind: upstream` starts from a configuration stored in the pinned upstream
checkout. The QA runtime adds the resolved extensions, generated connection SQL,
summary behavior and profile-scoped ignored tests.

```yaml
- name: sqlite
  tests: test/sql/*
  testConfig:
    kind: upstream
    path: test/configs/sqlite.json
```

## Runtime setup

A profile can currently request one maintained runtime setup:

```yaml
runtimeSetup: ducklake-postgres-15
```

This remains a closed, non-composable contract during phase 3. Service lifecycle
will be extracted into composable service contracts in the next refactoring
phase.

## Execution order

Profiles run in YAML order inside the battery job. The standard runner reads the
compiled profile list and performs the same sequence for every battery:

1. prepare the profile-specific SQLLogicTest configuration;
2. start the requested runtime setup;
3. execute the declared test filter;
4. validate that configured extension requirements were not silently skipped.

The runner never selects behavior from the battery name.
