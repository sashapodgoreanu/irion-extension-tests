from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from qa import load_config, resolve_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPOSITORY_ROOT / "config" / "extensions.yml"
PREPARE_BATTERY = REPOSITORY_ROOT / "scripts" / "prepare-test-battery.py"
PREPARE_PROFILE = REPOSITORY_ROOT / "scripts" / "prepare-standard-profile.py"
STANDARD_RUNNER = REPOSITORY_ROOT / "scripts" / "run-standard-tests.sh"
POSTGRES_RUNNER = REPOSITORY_ROOT / "scripts" / "run-postgres-scanner-tests.sh"


class ProfileRuntimeTestCase(unittest.TestCase):
    def prepare_case(self, case_name: str, root: Path) -> tuple[Path, dict]:
        plan = resolve_config(load_config(CONFIG_PATH))
        matrix_case = next(
            item for item in plan.matrix()["include"] if item["name"] == case_name
        )
        source = root / f"{case_name}.json"
        runtime = root / "runtime"
        source.write_text(json.dumps(matrix_case), encoding="utf-8")
        subprocess.run(
            [sys.executable, str(PREPARE_BATTERY), str(source), str(runtime)],
            check=True,
            cwd=REPOSITORY_ROOT,
        )
        return runtime, matrix_case

    def test_prepare_battery_generates_profile_specific_init_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime, _ = self.prepare_case("httpfs", Path(directory))
            profiles = json.loads((runtime / "profiles.json").read_text(encoding="utf-8"))
            self.assertEqual([item["name"] for item in profiles], ["sql", "autoload"])
            normal_init = (runtime / "init-profile-sql.sql").read_text(encoding="utf-8")
            autoload_init = (runtime / "init-profile-autoload.sql").read_text(
                encoding="utf-8"
            )
            self.assertIn("LOAD httpfs;", normal_init)
            self.assertNotIn("LOAD httpfs;", autoload_init)
            self.assertEqual(
                (runtime / "profiles.tsv").read_text(encoding="utf-8").splitlines(),
                ["sql\ttest/sql/*\tnone", "autoload\ttest/extension/*\tnone"],
            )

    def test_generated_profile_builds_sqllogictest_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, _ = self.prepare_case("httpfs", root)
            upstream = root / "upstream"
            upstream.mkdir()
            destination = root / "autoload.json"
            subprocess.run(
                [
                    sys.executable,
                    str(PREPARE_PROFILE),
                    str(runtime / "profiles.json"),
                    "autoload",
                    str(upstream),
                    str(destination),
                    str(runtime / "extensions.json"),
                    str(runtime / "profile-skips.json"),
                    str(runtime),
                ],
                check=True,
                cwd=REPOSITORY_ROOT,
            )
            config = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(config["statically_loaded_extensions"], ["core_functions"])
            self.assertNotIn("LOAD httpfs;", config["on_new_connection"])
            self.assertTrue(config["summarize_failures"])

    def test_upstream_profile_preserves_upstream_settings_and_adds_skips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, _ = self.prepare_case("ducklake", root)
            upstream = root / "upstream"
            source = upstream / "test" / "configs" / "sqlite.json"
            source.parent.mkdir(parents=True)
            source.write_text(
                json.dumps(
                    {
                        "statically_loaded_extensions": ["core_functions"],
                        "on_new_connection": "SET threads=1;",
                    }
                ),
                encoding="utf-8",
            )
            destination = root / "sqlite.json"
            subprocess.run(
                [
                    sys.executable,
                    str(PREPARE_PROFILE),
                    str(runtime / "profiles.json"),
                    "sqlite",
                    str(upstream),
                    str(destination),
                    str(runtime / "extensions.json"),
                    str(runtime / "profile-skips.json"),
                    str(runtime),
                ],
                check=True,
                cwd=REPOSITORY_ROOT,
            )
            config = json.loads(destination.read_text(encoding="utf-8"))
            self.assertIn("parquet", config["statically_loaded_extensions"])
            self.assertIn("ducklake", config["statically_loaded_extensions"])
            self.assertIn("SET threads=1;", config["on_new_connection"])
            self.assertEqual(
                config["skip_tests"][0]["paths"],
                ["test/sql/data_inlining/postgres_identifier_limit.test"],
            )

    def test_standard_runner_does_not_branch_on_battery_name(self) -> None:
        script = STANDARD_RUNNER.read_text(encoding="utf-8")
        self.assertNotIn('if [[ "${TEST_NAME}" ==', script)
        self.assertNotIn('elif [[ "${TEST_NAME}" ==', script)
        self.assertIn('case "${SETUP_KIND}" in', script)
        self.assertIn('done <"${PROFILES_TSV}"', script)

    def test_postgres_runner_owns_setup_before_profile_delegation(self) -> None:
        script = POSTGRES_RUNNER.read_text(encoding="utf-8")
        self.assertIn('SETUP_KIND=none bash "${STANDARD_RUNNER}"', script)
        self.assertNotIn(
            '"${UPSTREAM_ROOT}" \\\n  "${TEST_FILTER}" || status=$?',
            script,
        )


if __name__ == "__main__":
    unittest.main()
