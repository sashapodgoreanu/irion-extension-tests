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


def battery(*, accepted: bool = False, source_type: str = "remote") -> dict:
    capabilities = ["accepted-failure"] if accepted else []
    prerequisites = (
        [{"type": "google-bigquery"}, {"type": "external-cloud-account"}]
        if accepted
        else []
    )
    value = {
        "name": "httpfs",
        "runner": "standard",
        "sourceType": source_type,
        "duckdbVersion": "v1.5.5",
        "runtime": RUNTIME,
        "capabilities": capabilities,
        "prerequisites": prerequisites,
        "services": [],
        "extensions": [{"name": "httpfs"}],
        "profiles": [{"name": "sql", "tests": "test/sql/*", "services": []}],
        "ignoredTests": [],
    }
    if source_type == "remote":
        value.update(
            repository="duckdb/duckdb-httpfs",
            pin="a" * 40,
            submodules="recursive",
        )
    return value


def plan(*cases: dict, runtime: dict | None = None) -> dict:
    return {"runtime": runtime or RUNTIME, "cases": list(cases)}


def case_plan(*, accepted: bool = False, name: str = "httpfs") -> dict:
    return {
        "name": name,
        "execution": {
            "capabilities": ["accepted-failure"] if accepted else [],
        },
    }


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

    def test_parse_passing_summary_records_skips_as_metric(self) -> None:
        parsed = parse_unittest_log(
            "[122/122] (100%): test/sql/example.test\n"
            "All tests passed (2 skipped tests, 174165 assertions in 120 test cases)\n"
        )
        self.assertEqual(parsed["discovered"], 122)
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

    def test_result_fails_on_real_failed_test_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory)
            (log_dir / "unittest-sql.log").write_text(
                "test cases: 3 | 2 passed | 1 failed\n"
                "assertions: 10 | 9 passed | 1 failed\n",
                encoding="utf-8",
            )
            result = build_case_result(battery(), log_dir, exit_code=0)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["profiles"][0]["failed"], 1)
            self.assertFalse(list(Draft202012Validator(RESULT_SCHEMA).iter_errors(result)))

    def test_all_skipped_result_passes_and_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory)
            (log_dir / "unittest-sql.log").write_text(
                "[27/27] (100%): test/sql/azure.test\n"
                "All tests were skipped (total skipped 27)\n",
                encoding="utf-8",
            )
            result = build_case_result(battery(), log_dir, exit_code=0)
            summary = aggregate_results(plan(case_plan()), [result])

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["profiles"][0]["status"], "skipped")
            self.assertEqual(result["profiles"][0]["skipped"], 27)
            self.assertEqual(summary["status"], "passed")
            self.assertEqual(summary["passedCases"], ["httpfs"])
            self.assertNotIn("coverageViolations", summary)
            self.assertNotIn("skipViolations", summary)
            self.assertFalse(list(Draft202012Validator(SUMMARY_SCHEMA).iter_errors(summary)))

    def test_skip_count_change_never_changes_verdict(self) -> None:
        summaries = []
        for skipped in (1, 7, 50, 500):
            with tempfile.TemporaryDirectory() as directory:
                log_dir = Path(directory)
                discovered = skipped + 1
                (log_dir / "unittest-sql.log").write_text(
                    f"[{discovered}/{discovered}] (100%): test/sql/example.test\n"
                    f"All tests passed ({skipped} skipped tests, 8 assertions in 1 test case)\n",
                    encoding="utf-8",
                )
                result = build_case_result(battery(), log_dir, exit_code=0)
                summaries.append(aggregate_results(plan(case_plan()), [result]))

        self.assertTrue(all(item["status"] == "passed" for item in summaries))
        self.assertEqual(
            [item["results"][0]["profiles"][0]["skipped"] for item in summaries],
            [1, 7, 50, 500],
        )

    def test_composite_profile_metrics_are_aggregated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory)
            (log_dir / "unittest-sql-local.log").write_text(
                "[4/4] (100%): test/sql/local/example.test\n"
                "All tests passed (1 skipped test, 10 assertions in 3 test cases)\n",
                encoding="utf-8",
            )
            (log_dir / "unittest-sql-catalog.log").write_text(
                "[6/6] (100%): test/sql/catalog/example.test\n"
                "All tests passed (2 skipped tests, 20 assertions in 4 test cases)\n",
                encoding="utf-8",
            )
            result = build_case_result(battery(), log_dir, exit_code=0)
            profile = result["profiles"][0]
            self.assertEqual(profile["discovered"], 10)
            self.assertEqual(profile["passed"], 7)
            self.assertEqual(profile["failed"], 0)
            self.assertEqual(profile["skipped"], 3)
            self.assertEqual(result["status"], "passed")

    def test_external_prerequisite_not_run_is_explicit_and_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = build_case_result(
                battery(accepted=True),
                Path(directory),
                exit_code=1,
                reason="missing-google-cloud-credentials",
            )
            summary = aggregate_results(
                plan(case_plan(accepted=True)),
                [result],
            )
            self.assertEqual(result["status"], "accepted_failure")
            self.assertTrue(result["externalPrerequisite"]["notRun"])
            self.assertEqual(summary["status"], "passed")
            self.assertEqual(summary["externalPrerequisiteCases"], ["httpfs"])

    def test_aggregate_rejects_missing_and_real_failures(self) -> None:
        source_plan = plan(
            case_plan(),
            case_plan(accepted=True, name="bigquery"),
        )
        summary = aggregate_results(
            source_plan,
            [
                {
                    "caseId": "httpfs",
                    "status": "failed",
                    "acceptedFailure": False,
                    "externalPrerequisite": {"notRun": False},
                    "profiles": [],
                }
            ],
        )
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["failedCases"], ["httpfs"])
        self.assertEqual(summary["missingCases"], ["bigquery"])

    def test_summary_schema_accepts_windows_runtime(self) -> None:
        windows_runtime = {
            **RUNTIME,
            "operatingSystem": "windows",
            "githubRunner": "windows-2025",
        }
        result = {
            "caseId": "httpfs",
            "status": "passed",
            "acceptedFailure": False,
            "externalPrerequisite": {"notRun": False},
            "profiles": [{"name": "sql", "status": "skipped"}],
        }
        summary = aggregate_results(
            plan(case_plan(), runtime=windows_runtime),
            [result],
        )
        self.assertEqual(summary["runtime"]["operatingSystem"], "windows")
        self.assertFalse(list(Draft202012Validator(SUMMARY_SCHEMA).iter_errors(summary)))


if __name__ == "__main__":
    unittest.main()
