from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from qa.results import aggregate_results, build_case_result, parse_unittest_log

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RESULT_WRITER = REPOSITORY_ROOT / "scripts" / "write-test-result.py"
RESULT_AGGREGATOR = REPOSITORY_ROOT / "scripts" / "aggregate-test-results.py"
RESULT_SCHEMA = json.loads(
    (REPOSITORY_ROOT / "schemas" / "test-result-v1.schema.json").read_text(encoding="utf-8")
)
SUMMARY_SCHEMA = json.loads(
    (REPOSITORY_ROOT / "schemas" / "test-summary-v1.schema.json").read_text(encoding="utf-8")
)
RUNTIME = {
    "duckdbVersion": "v1.5.5",
    "ciToolsVersion": "v1.5.5",
    "operatingSystem": "linux",
    "architecture": "x86_64",
    "githubRunner": "ubuntu-24.04",
}
DEFAULT_POLICY = {
    "schemaVersion": 1,
    "defaults": {"minimumDiscovered": 1, "minimumExecuted": 1},
    "overrides": [],
}


def battery(*, accepted: bool = False, source_type: str = "remote") -> dict:
    capabilities = ["accepted-failure"] if accepted else []
    value = {
        "name": "httpfs",
        "runner": "standard",
        "sourceType": source_type,
        "duckdbVersion": "v1.5.5",
        "runtime": RUNTIME,
        "capabilities": capabilities,
        "services": [],
        "extensions": [{"name": "httpfs"}],
        "profiles": [{"name": "sql", "tests": "test/sql/*", "services": []}],
    }
    if source_type == "remote":
        value.update(
            repository="duckdb/duckdb-httpfs",
            pin="a" * 40,
            submodules="recursive",
        )
    return value


def plan(*cases: dict) -> dict:
    return {"runtime": RUNTIME, "cases": list(cases)}


class ResultTestCase(unittest.TestCase):
    def test_result_scripts_resolve_repository_package_when_executed_by_path(self) -> None:
        for script in (RESULT_WRITER, RESULT_AGGREGATOR):
            completed = subprocess.run(
                [sys.executable, str(script), "--help"],
                cwd=REPOSITORY_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("usage:", completed.stdout.lower())

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

    def test_parse_all_skipped_summary(self) -> None:
        parsed = parse_unittest_log(
            "[27/27] (100%): test/sql/azure.test\n"
            "All tests were skipped (total skipped 27)\n"
        )
        self.assertEqual(parsed["discovered"], 27)
        self.assertEqual(parsed["executed"], 0)
        self.assertEqual(parsed["passed"], 0)
        self.assertEqual(parsed["failed"], 0)
        self.assertEqual(parsed["skipped"], 27)

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
            self.assertEqual(result["runtime"], RUNTIME)
            self.assertEqual(result["upstream"]["type"], "remote")
            self.assertFalse(list(Draft202012Validator(RESULT_SCHEMA).iter_errors(result)))

    def test_self_source_result_has_no_remote_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory)
            (log_dir / "unittest-sql.log").write_text(
                "All tests passed (1 assertions in 1 test case)\n",
                encoding="utf-8",
            )
            result = build_case_result(
                battery(source_type="self"), log_dir, exit_code=0
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(
                result["upstream"],
                {"type": "self", "repository": None, "pin": None, "commit": None},
            )
            self.assertFalse(list(Draft202012Validator(RESULT_SCHEMA).iter_errors(result)))

    def test_composite_profile_logs_are_aggregated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory)
            (log_dir / "unittest-sql-local.log").write_text(
                "[88/88] (100%): test/sql/local/example.test\n"
                "All tests passed (8 skipped tests, 1703 assertions in 80 test cases)\n",
                encoding="utf-8",
            )
            (log_dir / "unittest-sql-fixture-catalog.log").write_text(
                "[334/334] (100%): test/sql/catalog/example.test\n"
                "All tests passed (18 skipped tests, 88075 assertions in 316 test cases)\n",
                encoding="utf-8",
            )

            result = build_case_result(battery(), log_dir, exit_code=0)
            profile = result["profiles"][0]

            self.assertEqual(result["status"], "passed")
            self.assertEqual(profile["status"], "passed")
            self.assertEqual(profile["discovered"], 422)
            self.assertEqual(profile["executed"], 396)
            self.assertEqual(profile["passed"], 396)
            self.assertEqual(profile["failed"], 0)
            self.assertEqual(profile["skipped"], 26)
            self.assertEqual(profile["assertions"], 89778)
            self.assertEqual(
                profile["log"],
                "unittest-sql-fixture-catalog.log,unittest-sql-local.log",
            )
            self.assertFalse(list(Draft202012Validator(RESULT_SCHEMA).iter_errors(result)))

    def test_all_skipped_result_is_structured_then_rejected_by_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory)
            (log_dir / "unittest-sql.log").write_text(
                "[27/27] (100%): test/sql/azure.test\n"
                "All tests were skipped (total skipped 27)\n",
                encoding="utf-8",
            )
            result = build_case_result(battery(), log_dir, exit_code=0)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["profiles"][0]["status"], "skipped")
            summary = aggregate_results(
                plan({"name": "httpfs", "execution": {"capabilities": []}}),
                [result],
                DEFAULT_POLICY,
            )
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["runtime"], RUNTIME)
            self.assertEqual(
                summary["coverageViolations"],
                [
                    {
                        "caseId": "httpfs",
                        "profile": "sql",
                        "metric": "executed",
                        "operator": ">=",
                        "actual": 0,
                        "expected": 1,
                    }
                ],
            )

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
        source_plan = plan(
            {"name": "httpfs", "execution": {"capabilities": []}},
            {"name": "bigquery", "execution": {"capabilities": ["accepted-failure"]}},
        )
        summary = aggregate_results(
            source_plan,
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
        source_plan = plan(
            {"name": "httpfs", "execution": {"capabilities": []}},
            {"name": "bigquery", "execution": {"capabilities": ["accepted-failure"]}},
        )
        summary = aggregate_results(
            source_plan,
            [
                {
                    "caseId": "httpfs",
                    "status": "passed",
                    "acceptedFailure": False,
                    "profiles": [
                        {
                            "name": "sql",
                            "status": "passed",
                            "discovered": 1,
                            "executed": 1,
                            "skipped": 0,
                        }
                    ],
                },
                {
                    "caseId": "bigquery",
                    "status": "accepted_failure",
                    "acceptedFailure": True,
                    "profiles": [{"status": "not_run"}],
                },
            ],
            DEFAULT_POLICY,
        )
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["acceptedFailureCases"], ["bigquery"])
        self.assertEqual(summary["coverageViolations"], [])
        self.assertEqual(summary["runtime"], RUNTIME)


if __name__ == "__main__":
    unittest.main()
