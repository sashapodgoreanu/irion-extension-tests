from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SHA = "969bc76276acec1c0a3922ff500d2ec3a1a3b037"


class DuckDBTwoBuildPinTests(unittest.TestCase):
    def test_build_sources_use_existing_pinned_gitlinks_without_refetch(self) -> None:
        shell = (ROOT / "scripts/build.sh").read_text(encoding="utf-8")
        windows = (ROOT / "scripts/build-windows.ps1").read_text(encoding="utf-8")
        self.assertNotIn("checkout_ref", shell)
        self.assertNotIn("Checkout-Ref", windows)
        self.assertNotIn("fetch --depth", shell)
        self.assertNotIn("'fetch'", windows)
        self.assertIn('refs/tags/${DUCKDB_VERSION}^{commit}', shell)
        self.assertIn('refs/tags/$DuckDBVersion^{commit}', windows)
        self.assertIn("CI_TOOLS_COMMIT", shell)
        self.assertIn("$CiToolsHead", windows)

    def test_duckdb_uses_a_release_and_ci_tools_uses_a_real_sha(self) -> None:
        config = yaml.safe_load((ROOT / "config/extensions.yml").read_text(encoding="utf-8"))
        self.assertEqual(config["duckdb"]["version"], "v2.0.0")
        self.assertEqual(config["duckdb"]["ciToolsVersion"], SHA)
        self.assertRegex(SHA, r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
