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
        windows_workflow = (ROOT / ".github/workflows/qa-windows.yml").read_text(
            encoding="utf-8"
        )
        windows_patch = "patches/duckdb-v2.0.0/union-by-name-windows-sdk.patch"
        patch_contents = (ROOT / windows_patch).read_text(encoding="utf-8")
        self.assertNotIn("checkout_ref", shell)
        self.assertNotIn("Checkout-Ref", windows)
        self.assertNotIn("fetch --depth", shell)
        self.assertNotIn("'fetch'", windows)
        self.assertIn('refs/tags/${DUCKDB_VERSION}^{commit}', shell)
        self.assertIn('refs/tags/$DuckDBVersion^{commit}', windows)
        self.assertIn("CI_TOOLS_COMMIT", shell)
        self.assertIn("$CiToolsHead", windows)
        self.assertIn(windows_patch, windows)
        self.assertIn("'cache-schema=v2'", windows_workflow)
        self.assertIn(windows_patch, windows_workflow)
        self.assertIn('"duckdb/common/windows_undefs.hpp"', patch_contents)

    def test_duckdb_uses_a_release_and_ci_tools_uses_a_real_sha(self) -> None:
        config = yaml.safe_load((ROOT / "config/extensions.yml").read_text(encoding="utf-8"))
        self.assertEqual(config["duckdb"]["version"], "v2.0.0")
        self.assertEqual(config["duckdb"]["ciToolsVersion"], SHA)
        self.assertRegex(SHA, r"^[0-9a-f]{40}$")

        build = (ROOT / "scripts/build.sh").read_text(encoding="utf-8")
        self.assertIn('DUCKDB_VERSION="${DUCKDB_VERSION:-v2.0.0}"', build)

    def test_linux_unittest_packages_shared_library_for_duckdb_two(self) -> None:
        build = (ROOT / "scripts/build.sh").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/qa-linux.yml").read_text(encoding="utf-8")
        self.assertIn("cp -a build/release/src/libduckdb.so* build/artifact/lib/", build)
        self.assertIn("export LD_LIBRARY_PATH=", build)
        self.assertIn("ldd build/artifact/bin/unittest", build)
        self.assertNotIn("ENABLE_EXTENSION_AUTOLOADING=1", build)
        self.assertNotIn("ENABLE_EXTENSION_AUTOINSTALL=1", build)
        self.assertIn("LD_LIBRARY_PATH: ${{ github.workspace }}/build/artifact/lib", workflow)
        self.assertIn("cache-schema=v4", workflow)
        self.assertIn("duckdb-runtime-v4-", workflow)
        self.assertIn("test -f build/artifact/lib/libduckdb.so", workflow)
        self.assertIn("Restore executable permissions and validate runtime dependencies", workflow)


if __name__ == "__main__":
    unittest.main()
