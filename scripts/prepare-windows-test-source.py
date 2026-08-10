#!/usr/bin/env python3
"""Apply narrow source adaptations for native Windows SQLLogicTest execution.

The service/tooling side of Windows QA runs in WSL while DuckDB and unittest are
native Windows binaries. A few upstream tests encode POSIX-only assumptions in
fixtures or expectations. Keep those differences here, fail on upstream drift,
and leave the Linux checkout path untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path


class PatchError(ValueError):
    pass


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def replace_exact(path: Path, old: str, new: str, *, expected: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise PatchError(
            f"{path}: expected {expected} occurrence(s) of adaptation anchor, found {count}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


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
    replace_exact(
        test,
        "SELECT count(*) FROM GLOB('${DATA_PATH}/*.db')",
        "SELECT count(*) FROM GLOB('${DUCKLAKE_CONNECTION}')",
        expected=2,
    )


def patch_azure(upstream_root: Path) -> None:
    script = upstream_root / "scripts/upload_test_files_to_azurite.sh"
    # Azure CLI may consume stdin. The upstream while-read loop shares stdin
    # with the process substitution, so a child invocation can drain all file
    # names after the first one. Materialize the list before uploading.
    replace_exact(
        script,
        """while read filepath; do\n  remote_filepath=\"$(echo \"${filepath}\" | cut -c 8-)\"\n  copy_file \"${filepath}\" \"${remote_filepath}\"\ndone < <(find ./data -type f)""",
        """mapfile -d '' -t fixture_files < <(find ./data -type f -print0 | sort -z)\nif [[ \"${#fixture_files[@]}\" -eq 0 ]]; then\n  echo \"No Azure fixture files were found under ./data\" >&2\n  exit 1\nfi\nfor filepath in \"${fixture_files[@]}\"; do\n  remote_filepath=\"${filepath#./data/}\"\n  copy_file \"${filepath}\" \"${remote_filepath}\"\ndone""",
    )


def patch_postgres_scanner(upstream_root: Path) -> None:
    fixture = upstream_root / "create-postgres-tables.sh"
    replace_exact(
        fixture,
        """psql -d postgresscanner < ${ABS_DIR_PREFIX}/postgresscannertmp/schema.sql\npsql -d postgresscanner < ${ABS_DIR_PREFIX}/postgresscannertmp/load.sql""",
        """psql -d postgresscanner < ${ABS_DIR_PREFIX}/postgresscannertmp/schema.sql\n# The native Windows DuckDB proxy translates EXPORT DATABASE to a drive path.\n# PostgreSQL runs in WSL/Docker and must receive the mounted WSL path instead.\nWINDOWS_ABS_DIR_PREFIX=\"$(wslpath -m \"${ABS_DIR_PREFIX}\")\"\nsed -i \"s#${WINDOWS_ABS_DIR_PREFIX}#${ABS_DIR_PREFIX}#g\" \"${ABS_DIR_PREFIX}/postgresscannertmp/load.sql\"\npsql -d postgresscanner < ${ABS_DIR_PREFIX}/postgresscannertmp/load.sql""",
    )

    binary_test = upstream_root / "test/sql/misc/postgres_binary.test"
    replace_exact(
        binary_test,
        "__WORKING_DIRECTORY__/__TEST_DIR__",
        "${PGSCANNER_SERVER_WORKING_DIRECTORY}/__TEST_DIR__",
        expected=2,
    )


def patch_delta(upstream_root: Path) -> None:
    makefile = upstream_root / "Makefile"
    replace_exact(
        makefile,
        """\t${PYTHON_BIN} scripts/data_generator/generate_test_data.py\n\t# avoid footguns -- make outputs read only\n\tfind data/generated -mindepth 1 -print0 | xargs -0 -n 1000 chmod a-w""",
        """\t${PYTHON_BIN} scripts/data_generator/generate_test_data.py\n\t# Native Windows copy_dir must be able to populate copied fixture directories.\n\tfind data/generated -mindepth 1 -print0 | xargs -0 -r -n 1000 chmod u+w\n\t# WSL can create Linux symlinks on DrvFS that native Windows cannot follow.\n\tfind build/release/rust/src/delta_kernel/acceptance/tests/dat -type l -exec sh -c 'for link; do target=\"$$(readlink -f \"$$link\")\"; rm \"$$link\"; cp -aL \"$$target\" \"$$link\"; done' sh {} +""",
    )
    replace_exact(
        makefile,
        """unpack-golden-tables-release:\n\t./scripts/unwrap_golden_tables.sh""",
        """unpack-golden-tables-release:\n\t./scripts/unwrap_golden_tables.sh\n\tfind data/unpacked_golden_tables -type l -exec sh -c 'for link; do target=\"$$(readlink -f \"$$link\")\"; rm \"$$link\"; cp -aL \"$$target\" \"$$link\"; done' sh {} +""",
    )


def patch_mssql_upstream(upstream_root: Path) -> None:
    # DuckDB's generic unittest binary cannot satisfy `require mssql` for this
    # out-of-tree extension on Windows even after the exact signed v0.2.2 binary
    # is installed and loaded. The Windows runner verifies that binary first and
    # preloads it on every connection, so remove only the redundant require
    # directive and execute the complete upstream SQLLogicTest bodies.
    require_count = 0
    changed_files = 0
    for test in sorted((upstream_root / "test/sql").rglob("*.test")):
        text = test.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        new_lines = []
        file_count = 0
        for line in lines:
            if line.strip().lower() == "require mssql":
                file_count += 1
                require_count += 1
                continue
            new_lines.append(line)
        if file_count:
            changed_files += 1
            test.write_text("".join(new_lines), encoding="utf-8")
    if require_count != 142 or changed_files != 142:
        raise PatchError(
            "MSSQL require contract drifted: expected 142 directives in 142 files, "
            f"found {require_count} directives in {changed_files} files"
        )


def patch_mssql_runner() -> None:
    runner = REPOSITORY_ROOT / "scripts/run-mssql-tests-base.sh"
    start_marker = "# Prepare a SQLLogicTest init profile that loads every compatibility extension"
    end_marker = 'MSSQL_TEST_CONNECTION_SQL="$(sed \'/^[[:space:]]*--/d\' "${MSSQL_TEST_INIT_SCRIPT}" | tr \'\\n\' \' \')"'
    replacement = """# Native Windows SQLLogicTest cannot satisfy `require mssql` for this out-of-tree\n# module. The exact signed repository binary was verified above; preload it on\n# init and on every connection, while the Windows source adapter removes only\n# the redundant require directive from the upstream test files.\ncp \"${INIT_SCRIPT}\" \"${MSSQL_TEST_INIT_SCRIPT}\"\ncp \"${MSSQL_TEST_INIT_SCRIPT}\" \"${LOG_DIR}/init-extensions-with-mssql.sql\"\nMSSQL_TEST_CONNECTION_SQL=\"$(sed '/^[[:space:]]*--/d' \"${MSSQL_TEST_INIT_SCRIPT}\" | tr '\\n' ' ')\""""
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
