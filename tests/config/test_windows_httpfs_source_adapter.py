from __future__ import annotations

import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUEST_COUNT_QUERY = (
    "FROM (FROM duckdb_logs_parsed('HTTP') SELECT count(*), "
    "sum(request.type == 'HEAD') head, sum(request.type == 'GET') get, "
    "sum(request.type == 'POST') post, sum(request.type == 'PUT') put "
    "GROUP BY context_id ORDER BY context_id) WHERE post == 0;"
)
LINUX_EXPECTATION = "3\t0\t3\t0\t0\n11\t0\t11\t0\t0\n9\t0\t9\t0\t0\n9\t0\t9\t0\t0"
WINDOWS_EXPECTATION = (
    "11\t0\t11\t0\t0\n11\t0\t11\t0\t0\n"
    "11\t0\t11\t0\t0\n11\t0\t11\t0\t0"
)


class TestWindowsHttpfsSourceAdapter(unittest.TestCase):
    def _write_test(self, root: Path, body: str) -> Path:
        test = root / "test" / "sql" / "copy" / "s3" / "glob_s3_paging.test_slow"
        test.parent.mkdir(parents=True)
        test.write_text(body, encoding="utf-8")
        return test

    def test_already_skipped_request_count_assertion_is_left_unchanged(self) -> None:
        adapter = runpy.run_path(str(ROOT / "scripts" / "prepare-windows-test-source.py"))
        upstream_test = (
            "# upstream has disabled this diagnostic assertion\n"
            "mode skip\n\n"
            f"query IIIII\n{REQUEST_COUNT_QUERY}\n----\n"
            "3\t0\t3\t0\t0\n11\t0\t11\t0\t0\n11\t0\t11\t0\t0\n"
            "11\t0\t11\t0\t0\n11\t0\t11\t0\t0\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            test = self._write_test(root, upstream_test)

            adapter["patch_httpfs"](root)

            self.assertEqual(test.read_text(encoding="utf-8"), upstream_test)

    def test_active_request_count_assertion_gets_windows_expectation(self) -> None:
        adapter = runpy.run_path(str(ROOT / "scripts" / "prepare-windows-test-source.py"))
        upstream_test = (
            f"query IIIII\n{REQUEST_COUNT_QUERY}\n----\n"
            f"{LINUX_EXPECTATION}\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            test = self._write_test(root, upstream_test)

            adapter["patch_httpfs"](root)
            adapter["patch_httpfs"](root)

            self.assertIn(WINDOWS_EXPECTATION, test.read_text(encoding="utf-8"))

    def test_unknown_active_request_count_expectation_fails_closed(self) -> None:
        adapter = runpy.run_path(str(ROOT / "scripts" / "prepare-windows-test-source.py"))
        upstream_test = (
            f"query IIIII\n{REQUEST_COUNT_QUERY}\n----\n"
            "changed expectation\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_test(root, upstream_test)

            with self.assertRaisesRegex(adapter["PatchError"], "adaptation anchor"):
                adapter["patch_httpfs"](root)


if __name__ == "__main__":
    unittest.main()
