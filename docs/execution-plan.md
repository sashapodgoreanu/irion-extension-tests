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
- the current runner, setup and SQLLogicTest filter;
- the resolved ordered extension set;
- ignored tests and their profile scope.

The GitHub Actions matrix is derived from the execution plan. During this phase,
the matrix payload remains byte-for-byte compatible with the previous resolver
contract, so test runners continue to consume the same JSON.

## Artifact contract

The document uses `schemaVersion: 1` and is validated by:

```text
schemas/execution-plan-v1.schema.json
```

The configure job uploads the plan as the `qa-execution-plan` workflow artifact
and reports its canonical SHA-256. The artifact makes the exact qualification
inputs inspectable without reconstructing them from workflow logs.

## Evolution rule

Future configuration changes should first be represented in the execution plan.
GitHub Actions and test runners should consume the compiled plan rather than
re-reading the authoring YAML independently.
