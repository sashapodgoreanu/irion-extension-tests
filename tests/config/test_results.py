from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from qa.results import aggregate_results, build_case_result, parse_unittest_log

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RESULT_SCHEMA = json.loads(
    (REPOSITORY_ROOT / "schemas" / "test-result-v1.schema.json").read_text(encoding="utf-8")
)
SUMMARY_SCHEMA = json.loads(
    (REPOSITORY_ROOT / "schemas" / "test-summary-v1.schema.json").read_text(encoding="utf-8")
)


def battery(*, accepted: bool = False) -> dict:
    capabilities = ["accepted-failure"] if accepted else []
    return {
        "name": "httpfs",
        "runner": "standard",
        "repository": "duckdb/duckdb-httpfs",
        "pin": "a" * 40,
        "duckdbVersion": "v1.5.4",
        "capabilities": capabilities,
        "services": [],
        "extensions": [{"name": "httpfs"}],
        "profiles": [{"name": "sql", "tests": "test/sql/*", "services": []}],
    }


class ResultTestCase(unittest.TestCase):
    def test_parse_passing_duckdb_summary(self) -> None:
        parsed = parse_unittest_log(
            "[122/122] (100%): test/sql/example.test\n"
            "All tests passed (2 skipped tests, 174165 assertions in 120 test cases)\n"
        )
        self.assertEqual(parsed["discovered"], 122)
        self.assertEqual(parsed["executed"], 120)
        self.assertEqual(parsed["passed"], 120)
        self.assertEqual(parsed["failed"], 0)
        self.assertEqual(parsed["skipped"], 2)

    def test_parse_failing_catch_summary(self) -> None:
        parsed = parse_unittest_log(
            "[133/133] (100%): test/sql/example.test\n"
            "test cases: 133 | 130 passed | 3 failed | 4 skipped\n"
            "assertions: 134669 | 134666 passed | 3 failed | 4 skipped\n"
        )
        self.assertEqual(parsed["discovered"], 133)
        self.assertEqual(parsed["executed"], 133)
        self.assertEqual(parsed["failed"], 3)
        self.assertEqual(parsed["assertions"], 134669)

    def test_result_fails_when_log_contains_failed_cases_even_with_zero_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory)
            (log_dir / "unittest-sql.log").write_text(
                "test cases: 3 | 2 passed | 1 failed\nassertions: 10 | 9 passed | 1 failed\n",
                encoding="utf-8",
            )
            result = build_case_result(battery(), log_dir, exit_code=0)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["profiles"][0]["failed"], 1)
            self.assertFalse(list(Draft202012Validator(RESULT_SCHEMA).iter_errors(result)))

    def test_accepted_failure_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = build_case_result(
                battery(accepted=True),
                Path(directory),
                exit_code=1,
                reason="missing-cloud-account",
            )
            self.assertEqual(result["status"], "accepted_failure")
            self.assertTrue(result["acceptedFailure"])

    def test_aggregate_rejects_missing_and_nonaccepted_failures(self) -> None:
        plan = {
            "cases": [
                {"name": "httpfs", "execution": {"capabilities": []}},
                {"name": "bigquery", "execution": {"capabilities": ["accepted-failure"]}},
            ]
        }
        summary = aggregate_results(
            plan,
            [
                {
                    "caseId": "httpfs",
                    "status": "failed",
                    "acceptedFailure": False,
                    "profiles": [],
                }
            ],
        )
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["failedCases"], ["httpfs"])
        self.assertEqual(summary["missingCases"], ["bigquery"])
        self.assertFalse(list(Draft202012Validator(SUMMARY_SCHEMA).iter_errors(summary)))

    def test_aggregate_accepts_only_declared_accepted_failure(self) -> None:
        plan = {
            "cases": [
                {"name": "httpfs", "execution": {"capabilities": []}},
                {"name": "bigquery", "execution": {"capabilities": ["accepted-failure"]}},
            ]
        }
        summary = aggregate_results(
            plan,
            [
                {
                    "caseId": "httpfs",
                    "status": "passed",
                    "acceptedFailure": False,
                    "profiles": [{"status": "passed"}],
                },
                {
                    "caseId": "bigquery",
                    "status": "accepted_failure",
                    "acceptedFailure": True,
                    "profiles": [{"status": "not_run"}],
                },
            ],
        )
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["acceptedFailureCases"], ["bigquery"])


if __name__ == "__main__":
    unittest.main()
