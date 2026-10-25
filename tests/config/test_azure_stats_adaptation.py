from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREPARER = ROOT / "scripts" / "prepare-azure-tests.py"
PRIVATE_LINE = (
    "analyzed_plan\t<REGEX>:" r".*HTTP Stats.*in\: \d[.]\d MiB.*"
    r"\#HEAD\: 4.*GET\: 0.*PUT\: 0.*\#POST\: 0.*"
)
PUBLIC_LINE = (
    "analyzed_plan\t<REGEX>:" r".*HTTP Stats.*in\: \d[.]\d MiB.*"
    r"\#HEAD\: 2.*GET\: 1.*PUT\: 0.*\#POST\: 0.*"
)


class AzureStatisticsAdaptationTests(unittest.TestCase):
    def fixture(self, parent: Path) -> Path:
        root = parent / "upstream"
        path = root / "test" / "sql" / "azure.test"
        path.parent.mkdir(parents=True)
        path.write_text(
            "# Azure extension test\n"
            "query II\nEXPLAIN ANALYZE SELECT 1;\n----\n"
            + PRIVATE_LINE + "\n"
            "query II\nEXPLAIN ANALYZE SELECT 1;\n----\n"
            + PRIVATE_LINE + "\n"
            "query II\nEXPLAIN ANALYZE SELECT 1;\n----\n"
            + PUBLIC_LINE + "\n",
            encoding="utf-8",
        )
        return root

    def run_preparer(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PREPARER), str(root)],
            capture_output=True, text=True, check=False,
        )

    def test_private_get_count_accepts_zero_or_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.fixture(Path(temp))
            path = root / "test" / "sql" / "azure.test"
            result = self.run_preparer(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = path.read_text(encoding="utf-8")
            self.assertEqual(updated.count(r"\#HEAD\: 4.*GET\: [01]"), 2)
            self.assertNotIn(PRIVATE_LINE, updated)
            self.assertIn(PUBLIC_LINE, updated)
            self.assertEqual(self.run_preparer(root).returncode, 0)
            self.assertEqual(updated, path.read_text(encoding="utf-8"))

    def test_unknown_upstream_fixture_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.fixture(Path(temp))
            path = root / "test" / "sql" / "azure.test"
            original = path.read_text(encoding="utf-8")
            path.write_text(original.replace(PRIVATE_LINE, "unexpected", 1), encoding="utf-8")
            result = self.run_preparer(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("required 2", result.stderr)


if __name__ == "__main__":
    unittest.main()
