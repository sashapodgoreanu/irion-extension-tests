# Repository contributor and agent instructions

## DuckDB extension source/binary pin invariant (mandatory)

This repository tests **the exact version of the extension binary distributed for
the configured DuckDB runtime**, not the newest upstream extension commit.

1. Before adding, enabling, or updating a test battery, use the **actual CI
   DuckDB binary**, run `INSTALL <extension>` with the intended core or
   community repository, and inspect `duckdb_extensions()` (especially
   `extension_name`, `extension_version`, `installed_from`). Record the
   evidence in `config/extension-binary-pins.yml`.
2. For an upstream extension reporting a Git SHA prefix (HTTPFS, DuckLake,
   postgres_scanner, Delta, Azure, Unity Catalog, etc.), resolve that prefix
   within the **correct upstream repository** to a complete immutable 40-char
   Git commit. Set `config/extensions.yml -> testBatteries.<battery>.pin`
   to precisely that commit; the pin must begin with the binary's reported SHA.
   Do **not** pin the latest `main` or a newer tag without proving the binary
   comes from that exact revision.
3. For release-versioned community extensions (BigQuery, MSSQL), use the exact
   released source tag reported by the binary and verify that the tag resolves
   to the recorded immutable commit. Normalization of an optional `v`
   prefix is allowed; do not compare a semver to a Git SHA or assume they match.
4. Preserve **fail-closed** source/binary alignment checks (in particular
   `scripts/run-postgres-scanner-tests.sh` and the MSSQL configured runner).
   Extend checks when a new extension is introduced. Never skip a mismatch,
   remove a test, accept an arbitrary version, or enable `-unsigned` to
   bypass failed verification.
5. Update `config/extensions.yml`, `config/extension-binary-pins.yml`,
   `docs/duckdb-2.0-migration.md` (or its successor), and regression tests
   **together** whenever an extension source or runtime changes. Run config
   tests and the actual extension battery in CI. A passing static test is not
   proof that functional tests pass.
6. Disabled batteries (currently Iceberg) and their exclusive prerequisites
   remain disabled. Do not reactivate or install them as a side effect of a pin
   update. Never merge into `main` without an explicit request.

If the correct matching source revision cannot be located, leave the existing
pin untouched, report the evidence and incompatibility, and do not claim that
the extension has been validated.
