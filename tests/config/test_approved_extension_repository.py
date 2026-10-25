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
        (self.platform_dir / "mssql.duckdb_extension.info").write_text(
            '{"name": "mssql"}', encoding="utf-8"
        )
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
        self.assertEqual(fixture.name, "mssql.duckdb_extension")
        self.assertEqual(fixture.read_bytes(), b"community-extension")
        self.assertEqual((fixture.parent / "mssql.duckdb_extension.info").read_text(encoding="utf-8"), '{"name": "mssql"}')
        self.assertEqual(fixture.parent.parent.name, "v1.5.5")
        self.assertEqual(fixture.parent.name, "windows_amd64")
        self.assertNotEqual(fixture.parent, self.platform_dir)

    def test_community_fixture_rejects_info_only_installation(self) -> None:
        (self.platform_dir / "mssql.duckdb_extension").unlink()
        with self.assertRaisesRegex(
            self.runner.RunnerError, "extension binary is missing"
        ):
            self.runner.copy_extension_fixture(
                self.platform_dir, self.runtime, "mssql", self.logger
            )

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


    def stage_community_fixture(self) -> Path:
        return self.runner.copy_extension_fixture(
            self.platform_dir, self.runtime, "mssql", self.logger
        )

    def test_community_load_policy_uses_signed_origin_and_fresh_homes(self) -> None:
        fixture = self.stage_community_fixture()
        calls: list[tuple[list[str], dict]] = []

        def simulate_cli(command, **kwargs):
            calls.append((command, kwargs))
            if kwargs["log_file"].name == "community-load-denied.log":
                kwargs["log_file"].write_text(
                    "community_extensions_allowed\nfalse\n"
                    'IO Error: Extension signature is either missing or invalid\n',
                    encoding="utf-8",
                )
                return 1
            return 0

        with mock.patch.object(self.runner, "run_logged", side_effect=simulate_cli):
            self.runner.validate_community_load_policy(
                self.root / "duckdb.exe", fixture, self.runtime, self.root, self.logger
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0][-1], "LOAD mssql;")
        self.assertNotIn("allow_community_extensions", calls[0][0][-1])
        self.assertIn("SET allow_community_extensions = false;", calls[1][0][-1])
        self.assertIn("LOAD mssql;", calls[1][0][-1])
        self.assertFalse(calls[1][1]["check"])
        self.assertNotIn("-unsigned", str(calls))
        homes = [Path(call[1]["env"]["HOME"]) for call in calls]
        self.assertNotEqual(homes[0], homes[1])
        for home in homes:
            installed = home / ".duckdb" / "extensions" / "v1.5.5" / "windows_amd64"
            self.assertEqual(
                (installed / "mssql.duckdb_extension").read_bytes(), b"community-extension"
            )
            self.assertEqual(
                (installed / "mssql.duckdb_extension.info").read_bytes(),
                (fixture.parent / "mssql.duckdb_extension.info").read_bytes(),
            )

    def test_community_fixture_requires_install_origin_info(self) -> None:
        (self.platform_dir / "mssql.duckdb_extension.info").unlink()
        with self.assertRaisesRegex(self.runner.RunnerError, "origin info is missing"):
            self.stage_community_fixture()

    def test_community_load_policy_rejects_unexpected_success(self) -> None:
        fixture = self.stage_community_fixture()
        with mock.patch.object(self.runner, "run_logged", return_value=0):
            with self.assertRaisesRegex(self.runner.RunnerError, "unexpectedly loaded"):
                self.runner.validate_community_load_policy(
                    self.root / "duckdb.exe", fixture, self.runtime, self.root, self.logger
                )

    def test_community_load_policy_rejects_unrelated_errors(self) -> None:
        fixture = self.stage_community_fixture()

        def simulate_cli(command, **kwargs):
            if kwargs["log_file"].name == "community-load-denied.log":
                kwargs["log_file"].write_text(
                    "community_extensions_allowed\nfalse\n"
                    'IO Error: Extension "mssql" not found.\n',
                    encoding="utf-8",
                )
                return 1
            return 0

        with mock.patch.object(self.runner, "run_logged", side_effect=simulate_cli):
            with self.assertRaisesRegex(
                self.runner.RunnerError, "reason other than its signature"
            ):
                self.runner.validate_community_load_policy(
                    self.root / "duckdb.exe", fixture, self.runtime, self.root, self.logger
                )

    def test_security_battery_rejects_skips_and_missing_test_discovery(self) -> None:
        log = self.root / "unittest-security.log"
        log.write_text(
            "test cases: 1 | 1 passed | 0 failed | 0 skipped\n",
            encoding="utf-8",
        )
        self.runner.assert_security_test_executed(log)

        log.write_text(
            "All tests passed (5 assertions in 1 test case)\n", encoding="utf-8"
        )
        self.runner.assert_security_test_executed(log)

        log.write_text("All tests were skipped (total skipped 1)\n", encoding="utf-8")
        with self.assertRaisesRegex(self.runner.RunnerError, "skipped"):
            self.runner.assert_security_test_executed(log)

        log.write_text(
            "test cases: 1 | 1 passed | 0 failed | 1 skipped\n"
            "require-env IRION_COMMUNITY_EXTENSION_PATH: 1\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(self.runner.RunnerError, "skipped"):
            self.runner.assert_security_test_executed(log)

        log.write_text("test cases: 0 | 0 passed | 0 failed\n", encoding="utf-8")
        with self.assertRaisesRegex(self.runner.RunnerError, "did not report"):
            self.runner.assert_security_test_executed(log)


if __name__ == "__main__":
    unittest.main()
