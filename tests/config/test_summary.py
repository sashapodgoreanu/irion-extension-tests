from __future__ import annotations

import unittest

from qa.summary import summary_markdown


class SummaryMarkdownTestCase(unittest.TestCase):
    def test_summary_uses_simple_test_metrics_table(self) -> None:
        summary = {
            "status": "passed",
            "runtime": {
                "operatingSystem": "linux",
                "architecture": "x86_64",
                "githubRunner": "ubuntu-24.04",
            },
            "expectedCases": ["mssql", "bigquery"],
            "results": [
                {
                    "caseId": "mssql",
                    "profiles": [
                        {
                            "name": "all",
                            "discovered": 142,
                            "passed": 129,
                            "failed": 0,
                            "skipped": 13,
                        }
                    ],
                },
                {
                    "caseId": "bigquery",
                    "profiles": [
                        {
                            "name": "all",
                            "discovered": None,
                            "passed": None,
                            "failed": None,
                            "skipped": None,
                        }
                    ],
                },
            ],
            "acceptedFailureCases": ["bigquery"],
            "externalPrerequisiteCases": ["bigquery"],
            "failedCases": [],
            "invalidCases": [],
            "missingCases": [],
            "unexpectedCases": [],
            "coverageViolations": [],
            "skipViolations": [],
        }

        markdown = summary_markdown(summary)

        self.assertIn(
            "| Case | Profile | Total tests | OK tests | KO tests | Skipped tests |",
            markdown,
        )
        self.assertIn("| `mssql` | `all` | 142 | 129 | 0 | 13 |", markdown)
        self.assertIn("| `bigquery` | `all` | — | — | — | — |", markdown)
        self.assertNotIn("Irion exclusions", markdown)
        self.assertNotIn("External prerequisite |", markdown)
        self.assertNotIn("Unexpected |", markdown)
        self.assertNotIn("Observed |", markdown)


if __name__ == "__main__":
    unittest.main()
