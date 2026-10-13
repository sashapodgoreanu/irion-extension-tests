"""Contract tests for the cross-platform security repository fixtures."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run-standard-tests.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("qa_native_standard_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ApprovedExtensionRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = load_runner()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.platform_dir = self.root / "home" / ".duckdb" / "extensions" / "v1.5.5" / "windows_amd64"
        self.platform_dir.mkdir(parents=True)
        (self.platform_dir / "httpfs.duckdb_extension").write_bytes(b"core-extension")
        (self.platform_dir / "mssql.duckdb_extension").write_bytes(b"community-extension")
        (self.platform_dir / "bigquery.duckdb_extension").write_bytes(b"other-community")
        self.runtime = self.root / "runtime"
        self.manifest = self.root / "extensions.json"
        self.manifest.write_text(
            json.dumps([
                {"name": "httpfs"},
                {"name": "mssql", "installFrom": "community"},
                {"name": "bigquery", "installFrom": "community"},
            ]),
            encoding="utf-8",
        )
        self.logger = mock.Mock()

    def test_approved_repository_keeps_core_and_removes_community(self) -> None:
        approved = self.runner.prepare_approved_extension_repo(
            self.platform_dir, self.runtime, "v1.5.5", self.manifest, self.logger
        )
        platform = approved / "v1.5.5" / "windows_amd64"
        self.assertEqual(
            (platform / "httpfs.duckdb_extension").read_bytes(), b"core-extension"
        )
        self.assertFalse((platform / "mssql.duckdb_extension").exists())
        self.assertFalse((platform / "bigquery.duckdb_extension").exists())
        self.assertEqual(
            (self.platform_dir / "mssql.duckdb_extension").read_bytes(),
            b"community-extension",
        )

    def test_community_fixture_is_byte_identical_to_installed_binary(self) -> None:
        fixture = self.runner.copy_extension_fixture(
            self.platform_dir, self.runtime, "mssql", self.logger
        )
        self.assertEqual(fixture.read_bytes(), b"community-extension")
        self.assertNotEqual(fixture.parent, self.platform_dir)

    def test_positive_probe_uses_separate_home_and_valid_sql_path(self) -> None:
        approved = self.runtime / "repository's approved"
        approved.mkdir(parents=True)
        log_dir = self.root / "logs"
        with mock.patch.object(self.runner, "run_logged") as logged:
            self.runner.validate_approved_extension_repo(
                self.root / "duckdb.exe", approved, self.runtime, log_dir, self.logger
            )
        args, kwargs = logged.call_args
        self.assertEqual(args[0][1:4], ["-csv", "-header", "-c"])
        sql = args[0][4]
        self.assertIn("repository''s approved", sql)
        self.assertIn("SET allow_community_extensions = false;", sql)
        self.assertIn("FORCE INSTALL httpfs;", sql)
        self.assertIn("LOAD httpfs;", sql)
        self.assertEqual(
            Path(kwargs["env"]["HOME"]),
            self.runtime / "approved-repo-probe-home",
        )
        self.assertEqual(kwargs["log_file"], log_dir / "approved-repository-probe.log")


if __name__ == "__main__":
    unittest.main()
