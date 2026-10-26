from __future__ import annotations

import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TestWindowsMssqlSourceAdapter(unittest.TestCase):
    def test_signed_runner_owns_mssql_requirement_adaptation(self) -> None:
        adapter = runpy.run_path(str(ROOT / "scripts" / "prepare-windows-test-source.py"))
        runner = (ROOT / "scripts" / "run-mssql-tests-base.sh").read_text(encoding="utf-8")

        self.assertNotIn("mssql", adapter["PATCHERS"])
        self.assertIn('gate.subn(', runner)
        self.assertIn('require-env MSSQL_QA_SIGNED_EXTENSION_AVAILABLE 1', runner)
        self.assertLess(
            runner.index("Dynamic MSSQL community-signed LOAD probe passed"),
            runner.index('gate.subn('),
        )

    def test_current_linux_runner_contract_is_accepted_and_windows_preload_is_applied(self) -> None:
        adapter = runpy.run_path(str(ROOT / "scripts" / "prepare-windows-test-source.py"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            runner = scripts / "run-mssql-tests-base.sh"
            runner.write_text(
                '\n'.join(
                    (
                        'cp "${INIT_SCRIPT}" "${MSSQL_TEST_INIT_SCRIPT}"',
                        'cp "${MSSQL_TEST_INIT_SCRIPT}" "${LOG_DIR}/init-extensions-with-mssql.sql"',
                        'MSSQL_TEST_CONNECTION_SQL="$(sed \'/^[[:space:]]*--/d\' "${MSSQL_TEST_INIT_SCRIPT}" | tr \'\\n\' \' \')"',
                        '    # MSSQL is intentionally absent because it is not compiled into unittest.',
                        '    "statically_loaded_extensions": ["core_functions", "parquet"],',
                    )
                )
                + '\n',
                encoding="utf-8",
            )
            adapter["patch_mssql_runner"].__globals__["REPOSITORY_ROOT"] = root

            adapter["patch_mssql_runner"]()
            adapter["patch_mssql_runner"]()

            updated = runner.read_text(encoding="utf-8")
            self.assertIn('"statically_loaded_extensions": ["core_functions", "parquet", "mssql"]', updated)
            self.assertIn('cp "${INIT_SCRIPT}" "${MSSQL_TEST_INIT_SCRIPT}"', updated)

    def test_unknown_runner_contract_fails_clearly(self) -> None:
        adapter = runpy.run_path(str(ROOT / "scripts" / "prepare-windows-test-source.py"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "run-mssql-tests-base.sh").write_text("# changed upstream contract\n", encoding="utf-8")
            adapter["patch_mssql_runner"].__globals__["REPOSITORY_ROOT"] = root

            with self.assertRaisesRegex(adapter["PatchError"], "MSSQL runner init contract"):
                adapter["patch_mssql_runner"]()


if __name__ == "__main__":
    unittest.main()
