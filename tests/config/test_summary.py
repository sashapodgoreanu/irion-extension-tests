from __future__ import annotations

import unittest

from qa.summary import summary_markdown


class SummaryMarkdownTestCase(unittest.TestCase):
    def test_summary_uses_human_quality_metrics_without_skip_policy(self) -> None:
        summary = {
            "status": "passed",
            "runtime": {
                "operatingSystem": "windows",
                "architecture": "x86_64",
                "githubRunner": "windows-2025",
            },
            "expectedCases": ["mssql", "bigquery"],
            "results": [
                {
                    "caseId": "mssql",
                    "profiles": [
                        {
                            "name": "all",
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
            "duplicateCases": [],
        }

        markdown = summary_markdown(summary)

        self.assertIn(
            "| Case | Profile | OK tests | KO tests | Skipped / not executed |",
            markdown,
        )
        self.assertIn("| `mssql` | `all` | 129 | 0 | 13 |", markdown)
        self.assertIn("| `bigquery` | `all` | — | — | — |", markdown)
        self.assertIn(
            "Skipped/non-executed counts are informational and do not affect the verdict.",
            markdown,
        )
        self.assertNotIn("Coverage violations", markdown)
        self.assertNotIn("Skip policy violations", markdown)
        self.assertNotIn("Authorized skips", markdown)


if __name__ == "__main__":
    unittest.main()
