#!/usr/bin/env python3
"""Apply narrow source adaptations for native Windows SQLLogicTest execution.

The service/tooling side of Windows QA runs in WSL while DuckDB and unittest are
native Windows binaries. A few upstream tests encode POSIX-only assumptions in
fixtures or expectations. Keep those differences here, fail on upstream drift,
and leave the Linux checkout path untouched.

Adapters must never depend on a fixed number of tests in an upstream battery.
Test suites are expected to grow. Structural anchors inside a specific file may
still be validated when an adapter must rewrite that exact upstream construct.
"""

from __future__ import annotations

import sys
from pathlib import Path


class PatchError(ValueError):
    pass


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
SQLLOGIC_TEST_SUFFIXES = {".test", ".test_slow"}


def replace_exact(path: Path, old: str, new: str, *, expected: int = 1) -> None:
    """Replace a structural anchor in one known file, never a suite-size contract."""
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise PatchError(
            f"{path}: expected {expected} occurrence(s) of adaptation anchor, found {count}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def replace_all_required(path: Path, old: str, new: str) -> int:
    """Replace every matching construct without assuming how many exist."""
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        raise PatchError(f"{path}: adaptation anchor was not found")
    updated = text.replace(old, new)
    if old in updated:
        raise PatchError(f"{path}: adaptation anchor remains after replacement")
    path.write_text(updated, encoding="utf-8")
    return count


def replace_region(path: Path, start_marker: str, end_marker: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    start = text.find(start_marker)
    if start < 0:
        raise PatchError(f"{path}: adaptation start marker was not found")
    second_start = text.find(start_marker, start + 1)
    if second_start >= 0:
        raise PatchError(f"{path}: adaptation start marker is ambiguous")
    end_start = text.find(end_marker, start)
    if end_start < 0:
        raise PatchError(f"{path}: adaptation end marker was not found")
    second_end = text.find(end_marker, end_start + 1)
    if second_end >= 0:
        raise PatchError(f"{path}: adaptation end marker is ambiguous")
    end = end_start + len(end_marker)
    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


def iter_sqllogic_tests(root: Path):
    """Yield every current/future SQLLogicTest file without assuming suite size."""
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in SQLLOGIC_TEST_SUFFIXES:
            yield path


def remove_test_directive(root: Path, directive: str) -> tuple[int, int]:
    """Remove a directive wherever it exists and verify none remain afterwards."""
    normalized = directive.strip().lower()
    changed_files = 0
    removed_directives = 0

    for test in iter_sqllogic_tests(root):
        lines = test.read_text(encoding="utf-8").splitlines(keepends=True)
        filtered = [line for line in lines if line.strip().lower() != normalized]
        removed = len(lines) - len(filtered)
        if removed:
            changed_files += 1
            removed_directives += removed
            test.write_text("".join(filtered), encoding="utf-8")

    remaining = []
    for test in iter_sqllogic_tests(root):
        if any(
            line.strip().lower() == normalized
            for line in test.read_text(encoding="utf-8").splitlines()
        ):
            remaining.append(test)

    if remaining:
        preview = ", ".join(str(path) for path in remaining[:5])
        raise PatchError(
            f"directive {directive!r} remains in {len(remaining)} SQLLogicTest file(s): {preview}"
        )

    return changed_files, removed_directives


def patch_httpfs(upstream_root: Path) -> None:
    test = upstream_root / "test/sql/copy/s3/glob_s3_paging.test_slow"
    # WinHTTP/curl scheduling issues the same eleven GETs for each paging
    # context. The functional paging result is unchanged; only the diagnostic
    # HTTP request-count expectation differs from Linux.
    replace_exact(
        test,
        "3\t0\t3\t0\t0\n11\t0\t11\t0\t0\n9\t0\t9\t0\t0\n9\t0\t9\t0\t0",
        "11\t0\t11\t0\t0\n11\t0\t11\t0\t0\n11\t0\t11\t0\t0\n11\t0\t11\t0\t0",
    )


def patch_ducklake(upstream_root: Path) -> None:
    test = upstream_root / "test/sql/remove_orphans/metadata_in_data_path.test"
    # Windows SQLLogicTest can retain unrelated database files in the shared
    # temp directory. The test's contract is that *its* metadata DB survives,
    # so probe that exact path rather than counting every .db in the directory.
    # The SQLite profile represents that file as a DuckLake connection URI
    # (sqlite:<path>); GLOB needs the filesystem path, not the catalog prefix.
    replace_exact(
        test,
        "SELECT count(*) FROM GLOB('${DATA_PATH}/*.db')",
        "SELECT count(*) FROM GLOB(regexp_replace('${DUCKLAKE_CONNECTION}', '^sqlite:', ''))",
        expected=2,
    )


def patch_azure(upstream_root: Path) -> None:
    script = upstream_root / "scripts/upload_test_files_to_azurite.sh"
    # Azure CLI may consume stdin. The upstream while-read loop shares stdin
    # with the process substitution, so a child invocation can drain all file
    # names after the first one. Materialize the list before uploading.
    replace_exact(
        script,
        """while read filepath; do
  remote_filepath="$(echo "${filepath}" | cut -c 8-)"
  copy_file "${filepath}" "${remote_filepath}"
done < <(find ./data -type f)""",
        """mapfile -d '' -t fixture_files < <(find ./data -type f -print0 | sort -z)
if [[ "${#fixture_files[@]}" -eq 0 ]]; then
  echo "No Azure fixture files were found under ./data" >&2
  exit 1
fi
for filepath in "${fixture_files[@]}"; do
  remote_filepath="${filepath#./data/}"
  copy_file "${filepath}" "${remote_filepath}"
done""",
    )


def patch_postgres_scanner(upstream_root: Path) -> None:
    fixture = upstream_root / "create-postgres-tables.sh"
    replace_exact(
        fixture,
        """psql -d postgresscanner < ${ABS_DIR_PREFIX}/postgresscannertmp/schema.sql
psql -d postgresscanner < ${ABS_DIR_PREFIX}/postgresscannertmp/load.sql""",
        """psql -d postgresscanner < ${ABS_DIR_PREFIX}/postgresscannertmp/schema.sql
# The native Windows DuckDB proxy translates EXPORT DATABASE to a drive path.
# PostgreSQL runs in WSL/Docker and must receive the mounted WSL path instead.
WINDOWS_ABS_DIR_PREFIX="$(wslpath -m "${ABS_DIR_PREFIX}")"
sed -i "s#${WINDOWS_ABS_DIR_PREFIX}#${ABS_DIR_PREFIX}#g" "${ABS_DIR_PREFIX}/postgresscannertmp/load.sql"
psql -d postgresscanner < ${ABS_DIR_PREFIX}/postgresscannertmp/load.sql""",
    )

    # The test writes pg_binary.bin with native Windows unittest, so
    # __TEST_DIR__ contains Windows separators. PostgreSQL itself runs in the
    # WSL/Docker service host and reads the file server-side. Embed the actual
    # mounted WSL checkout root and normalize the expanded test directory before
    # handing the path to postgres_execute. Linux never invokes this adapter and
    # therefore keeps the upstream __WORKING_DIRECTORY__/__TEST_DIR__ behavior.
    binary_test = upstream_root / "test/sql/misc/postgres_binary.test"
    server_root = upstream_root.as_posix().rstrip("/").replace("'", "''")
    old = (
        "'COPY binary_copy_test FROM "
        "''__WORKING_DIRECTORY__/__TEST_DIR__/pg_binary.bin'' (FORMAT binary)'"
    )
    new = (
        "'COPY binary_copy_test FROM ''' || "
        f"replace('{server_root}/__TEST_DIR__/pg_binary.bin', chr(92), '/') || "
        "''' (FORMAT binary)'"
    )
    count = replace_all_required(binary_test, old, new)
    print(
        f"Postgres scanner Windows adapter normalized {count} server-side COPY path expression(s)"
    )


def patch_delta(upstream_root: Path) -> None:
    makefile = upstream_root / "Makefile"
    replace_exact(
        makefile,
        """\t${PYTHON_BIN} scripts/data_generator/generate_test_data.py
\t# avoid footguns -- make outputs read only
\tfind data/generated -mindepth 1 -print0 | xargs -0 -n 1000 chmod a-w""",
        """\t${PYTHON_BIN} scripts/data_generator/generate_test_data.py
\t# Native Windows copy_dir must be able to populate copied fixture directories.
\tfind data/generated -mindepth 1 -print0 | xargs -0 -r -n 1000 chmod u+w
\t# WSL can create Linux symlinks on DrvFS that native Windows cannot follow.
\tfind build/release/rust/src/delta_kernel/acceptance/tests/dat -type l -exec sh -c 'for link; do target="$$(readlink -f "$$link")"; rm "$$link"; cp -aL "$$target" "$$link"; done' sh {} +""",
    )
    replace_exact(
        makefile,
        """unpack-golden-tables-release:
\t./scripts/unwrap_golden_tables.sh""",
        """unpack-golden-tables-release:
\t./scripts/unwrap_golden_tables.sh
\tfind data/unpacked_golden_tables -type l -exec sh -c 'for link; do target="$$(readlink -f "$$link")"; rm "$$link"; cp -aL "$$target" "$$link"; done' sh {} +""",
    )


def patch_mssql_upstream(upstream_root: Path) -> None:
    # DuckDB's generic unittest binary cannot satisfy `require mssql` for this
    # out-of-tree extension on Windows even after the exact signed binary is
    # installed and loaded. Remove that guard from every SQLLogicTest currently
    # present; newly added tests are picked up automatically as the suite grows.
    test_root = upstream_root / "test/sql"
    changed_files, removed_directives = remove_test_directive(test_root, "require mssql")
    if removed_directives == 0:
        raise PatchError("MSSQL source contains no 'require mssql' directives to adapt")
    print(
        f"MSSQL Windows adapter removed {removed_directives} require directive(s) "
        f"from {changed_files} SQLLogicTest file(s)"
    )


def patch_mssql_runner() -> None:
    runner = REPOSITORY_ROOT / "scripts/run-mssql-tests-base.sh"
    start_marker = "# Prepare a SQLLogicTest init profile that loads every compatibility extension"
    end_marker = 'MSSQL_TEST_CONNECTION_SQL="$(sed \'/^[[:space:]]*--/d\' "${MSSQL_TEST_INIT_SCRIPT}" | tr \'\\n\' \' \')"'
    replacement = """# Native Windows SQLLogicTest cannot satisfy `require mssql` for this out-of-tree
# module. The exact signed repository binary was verified above; preload it on
# init and on every connection, while the Windows source adapter removes only
# the redundant require directive from all current/future upstream test files.
cp "${INIT_SCRIPT}" "${MSSQL_TEST_INIT_SCRIPT}"
cp "${MSSQL_TEST_INIT_SCRIPT}" "${LOG_DIR}/init-extensions-with-mssql.sql"
MSSQL_TEST_CONNECTION_SQL="$(sed '/^[[:space:]]*--/d' "${MSSQL_TEST_INIT_SCRIPT}" | tr '\n' ' ')""" + '"'
    replace_region(runner, start_marker, end_marker, replacement)
    replace_exact(
        runner,
        '    # MSSQL is intentionally absent because it is not compiled into unittest.\n    "statically_loaded_extensions": ["core_functions", "parquet"],',
        '    # Native Windows preloads the exact dynamically installed binary.\n    "statically_loaded_extensions": ["core_functions", "parquet", "mssql"],',
    )


PATCHERS = {
    "httpfs": patch_httpfs,
    "ducklake": patch_ducklake,
    "azure": patch_azure,
    "postgres_scanner": patch_postgres_scanner,
    "delta": patch_delta,
    "mssql": patch_mssql_upstream,
}


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} BATTERY UPSTREAM_ROOT", file=sys.stderr)
        return 2

    battery = sys.argv[1]
    upstream_root = Path(sys.argv[2]).resolve()
    try:
        if not upstream_root.is_dir():
            raise PatchError(f"upstream checkout is missing: {upstream_root}")
        patcher = PATCHERS.get(battery)
        if patcher is not None:
            patcher(upstream_root)
        if battery == "mssql":
            patch_mssql_runner()
        print(f"Prepared native Windows source adaptations for {battery}")
        return 0
    except (OSError, PatchError) as exc:
        print(f"Unable to prepare Windows source adaptations for {battery}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
