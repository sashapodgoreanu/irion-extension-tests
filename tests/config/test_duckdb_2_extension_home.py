from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class DuckDBTwoExtensionHomeTests(unittest.TestCase):
    def test_bash_preserves_installed_extensions_for_all_test_profiles(self) -> None:
        script = (ROOT / "scripts/run-standard-tests.sh").read_text(encoding="utf-8")
        self.assertIn('export HOME="${RUNTIME_ROOT}/home"', script)
        self.assertIn('prepare_local_extension_repo', script)
        self.assertEqual(script.count("--keep-home"), 2)
        self.assertEqual(script.count('--test-config "${config}"'), 2)

    def test_native_preserves_battery_home_on_linux_and_windows(self) -> None:
        script = (ROOT / "scripts/run-standard-tests.py").read_text(encoding="utf-8")
        self.assertIn('env["HOME"] = str(runtime_home)', script)
        self.assertIn('env["USERPROFILE"] = str(runtime_home)', script)
        self.assertIn('child_environment(runtime_root / "home")', script)
        self.assertIn('validate_probe(duckdb, install_sql, init_sql', script)
        self.assertEqual(script.count('"--keep-home",'), 2)
        self.assertEqual(script.count('str(unittest),'), 2)


if __name__ == "__main__":
    unittest.main()
