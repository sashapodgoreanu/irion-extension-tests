from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class WindowsDuckLakeRuntimeTest(unittest.TestCase):
    def test_ducklake_runner_uses_and_cleans_a_short_source_junction(self) -> None:
        runner = (ROOT / "scripts" / "run-windows-wsl-battery.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("qa-ducklake-src", runner)
        self.assertIn("$runnerSourceRoot = $shortSourceAlias", runner)
        self.assertIn("& python $runner $BatteryName $runnerSourceRoot", runner)
        self.assertIn("removed DuckLake short source alias", runner)

    def test_standard_runner_preserves_windows_junction_paths(self) -> None:
        runner = (ROOT / "scripts" / "run-standard-tests.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('if os.name == "nt":', runner)
        self.assertIn("upstream_root = upstream_root_arg.absolute()", runner)
        self.assertIn("upstream_root = upstream_root_arg.resolve()", runner)


if __name__ == "__main__":
    unittest.main()
