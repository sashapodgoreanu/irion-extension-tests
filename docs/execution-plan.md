# QA execution plan

`config/extensions.yml` remains the human-authored source of truth. The configure
stage validates it and compiles a versioned machine-readable artifact:

```text
build/plan/execution-plan.json
```

The plan is the boundary between configuration and orchestration. It records:

- the DuckDB and extension-ci-tools runtime versions;
- every enabled test case;
- the immutable upstream repository and pin;
- the selected runner and battery-level setup;
- the ordered declarative profiles executed by the case;
- each profile's test filter, SQLLogicTest configuration and runtime setup;
- the resolved ordered extension set;
- ignored tests and their profile scope.

The GitHub Actions matrix is derived from the execution plan. The legacy `tests`
field remains in each matrix row for the specialized PostgreSQL and MSSQL runners;
it is derived from the first profile. The standard runner consumes the complete
`profiles` collection and does not branch on the battery name.

## Artifact contract

The current document uses `schemaVersion: 2` and is validated by:

```text
schemas/execution-plan-v2.schema.json
```

The configure job uploads the plan as the `qa-execution-plan` workflow artifact
and reports its canonical SHA-256. The artifact makes the exact qualification
inputs inspectable without reconstructing them from workflow logs.

## Evolution rule

Future configuration changes should first be represented in the execution plan.
GitHub Actions and test runners should consume the compiled plan rather than
re-reading the authoring YAML independently.
