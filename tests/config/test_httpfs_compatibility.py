from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROFILE_HELPER = REPOSITORY_ROOT / "scripts" / "prepare-standard-profile.py"

spec = importlib.util.spec_from_file_location("prepare_standard_profile", PROFILE_HELPER)
assert spec is not None and spec.loader is not None
prepare_standard_profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_standard_profile)


class HttpfsCompatibilityTestCase(unittest.TestCase):
    def test_only_request_count_assertion_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            test_file = (
                root
                / "test"
                / "sql"
                / "copy"
                / "s3"
                / "glob_s3_paging.test_slow"
            )
            test_file.parent.mkdir(parents=True)
            test_file.write_text(
                """query I
SELECT count(*) FROM glob('s3://test-bucket/paging/*');
----
8000

query IIIII
FROM (FROM duckdb_logs_parsed('HTTP') SELECT count(*), sum(request.type == 'HEAD') head GROUP BY context_id ORDER BY context_id) WHERE post == 0;
----
3\t0\t3\t0\t0
""",
                encoding="utf-8",
            )

            prepare_standard_profile.align_httpfs_request_count_test(root)
            first = test_file.read_text(encoding="utf-8")
            prepare_standard_profile.align_httpfs_request_count_test(root)
            second = test_file.read_text(encoding="utf-8")

            self.assertEqual(first, second)
            self.assertIn("----\n8000\n\n# QA compatibility:", second)
            self.assertIn("mode skip\n\nquery IIIII\nFROM", second)
            self.assertEqual(second.count("mode skip"), 1)

    def test_changed_upstream_assertion_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            test_file = (
                root
                / "test"
                / "sql"
                / "copy"
                / "s3"
                / "glob_s3_paging.test_slow"
            )
            test_file.parent.mkdir(parents=True)
            test_file.write_text("query I\nSELECT 1\n----\n1\n", encoding="utf-8")

            with self.assertRaises(prepare_standard_profile.ProfileError):
                prepare_standard_profile.align_httpfs_request_count_test(root)


if __name__ == "__main__":
    unittest.main()
