from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from qa import load_config, resolve_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPOSITORY_ROOT / "config" / "extensions.yml"
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "extension-qa.yml"
PREPARE_BATTERY = REPOSITORY_ROOT / "scripts" / "prepare-test-battery.py"
PREPARE_PROFILE = REPOSITORY_ROOT / "scripts" / "prepare-standard-profile.py"
STANDARD_RUNNER = REPOSITORY_ROOT / "scripts" / "run-standard-tests.sh"
BATTERY_RUNNER = REPOSITORY_ROOT / "scripts" / "run-test-battery.sh"
POSTGRES_RUNNER = REPOSITORY_ROOT / "scripts" / "run-postgres-scanner-tests.sh"
SERVICE_MANAGER = REPOSITORY_ROOT / "scripts" / "service-manager.sh"
MSSQL_PATCHER = REPOSITORY_ROOT / "scripts" / "prepare-mssql-configured-runner.py"


class ServiceRuntimeTestCase(unittest.TestCase):
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

    def test_httpfs_runtime_contains_composable_service_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime, matrix_case = self.prepare_case("httpfs", Path(directory))
            services = json.loads((runtime / "services.json").read_text(encoding="utf-8"))
            self.assertEqual(services, matrix_case["services"])
            self.assertEqual(
                [item["type"] for item in services],
                ["python-http", "squid", "httpfs-minio"],
            )
            self.assertEqual(
                json.loads((runtime / "capabilities.json").read_text(encoding="utf-8")),
                ["squid", "docker-compose"],
            )
            self.assertEqual(
                json.loads((runtime / "profile-services-sql.json").read_text(encoding="utf-8")),
                [],
            )
            self.assertEqual(
                (runtime / "profiles.tsv").read_text(encoding="utf-8").splitlines(),
                ["sql\ttest/sql/*"],
            )
            env_text = (runtime / "battery.env").read_text(encoding="utf-8")
            self.assertNotIn("SETUP_KIND", env_text)

    def test_ducklake_postgres_service_is_profile_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime, _ = self.prepare_case("ducklake", Path(directory))
            self.assertEqual(
                json.loads((runtime / "services.json").read_text(encoding="utf-8")), []
            )
            services = json.loads(
                (runtime / "profile-services-postgres.json").read_text(encoding="utf-8")
            )
            self.assertEqual(services[0]["type"], "postgres")
            self.assertEqual(services[0]["version"], "15")
            self.assertEqual(services[0]["database"], "ducklakedb")
            self.assertEqual(
                json.loads((runtime / "profile-services-autoload.json").read_text(encoding="utf-8")),
                [],
            )

    def test_bigquery_prerequisite_is_separate_from_services(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime, _ = self.prepare_case("bigquery", Path(directory))
            self.assertEqual(
                json.loads((runtime / "services.json").read_text(encoding="utf-8")), []
            )
            self.assertEqual(
                json.loads((runtime / "prerequisites.json").read_text(encoding="utf-8")),
                [
                    {"type": "google-bigquery"},
                    {"type": "external-cloud-account"},
                ],
            )
            self.assertEqual(
                json.loads((runtime / "capabilities.json").read_text(encoding="utf-8")),
                ["google-cloud-auth", "accepted-failure"],
            )

    def test_generated_profile_still_builds_sqllogictest_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, _ = self.prepare_case("httpfs", root)
            upstream = root / "upstream"
            upstream.mkdir()
            destination = root / "sql.json"
            subprocess.run(
                [
                    sys.executable,
                    str(PREPARE_PROFILE),
                    str(runtime / "profiles.json"),
                    "sql",
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
            self.assertEqual(
                config["statically_loaded_extensions"], ["core_functions", "parquet"]
            )
            self.assertIn("LOAD httpfs;", config["on_new_connection"])
            self.assertIn("LOAD bigquery;", config["on_new_connection"])

    def test_standard_runner_uses_profile_service_manager(self) -> None:
        script = STANDARD_RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("SETUP_KIND", script)
        self.assertNotIn('case "${runtime_setup}"', script)
        self.assertIn('source "${SERVICE_MANAGER}"', script)
        self.assertIn('qa_service_start_file "${profile_services}"', script)
        self.assertIn('qa_service_stop_all', script)
        profile_plan = 'mapfile -t profile_rows <"${PROFILES_TSV}"'
        self.assertIn(profile_plan, script)
        self.assertIn('for profile_row in "${profile_rows[@]}"; do', script)
        self.assertNotIn('done <"${PROFILES_TSV}"', script)
        self.assertLess(
            script.index(profile_plan),
            script.index('qa_service_start_file "${profile_services}"'),
        )

    def test_battery_runner_owns_battery_service_and_result_lifecycle(self) -> None:
        script = BATTERY_RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("SETUP_KIND", script)
        self.assertIn('qa_prerequisite_check_file', script)
        self.assertIn('trap finalize_result EXIT', script)
        self.assertIn('qa_service_stop_all || true', script)
        self.assertIn('python3 "${RESULT_WRITER}"', script)
        self.assertIn('qa_service_start_file "${BATTERY_RUNTIME_CONFIG_DIR}/services.json"', script)
        self.assertLess(
            script.index("trap finalize_result EXIT"),
            script.index('qa_service_start_file "${BATTERY_RUNTIME_CONFIG_DIR}/services.json"'),
        )
        self.assertIn('export HOME="${RUNTIME_ROOT}/home"', script)

    def test_postgres_runner_no_longer_overrides_setup_contract(self) -> None:
        script = POSTGRES_RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("SETUP_KIND", script)
        self.assertIn('bash "${STANDARD_RUNNER}"', script)
        self.assertIn("PostgreSQL test service did not become ready", script)

    def test_workflow_selects_dependencies_from_capabilities(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertNotIn("matrix.setup", workflow)
        self.assertIn("contains(matrix.capabilities, 'google-cloud-auth')", workflow)
        self.assertIn("contains(matrix.capabilities, 'squid')", workflow)
        self.assertIn("contains(matrix.capabilities, 'postgres-client')", workflow)
        self.assertIn("contains(matrix.capabilities, 'docker-compose')", workflow)
        self.assertIn("uses: google-github-actions/auth@v3", workflow)
        self.assertIn(
            "continue-on-error: ${{ contains(matrix.capabilities, 'accepted-failure') }}",
            workflow,
        )
        self.assertNotIn("action-setup-postgres", workflow)

    def test_prerequisite_checker_accepts_empty_and_rejects_missing_bigquery_env(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = root / "empty.json"
            empty.write_text("[]\n", encoding="utf-8")
            subprocess.run(
                ["bash", "-c", f'source "{SERVICE_MANAGER}"; qa_prerequisite_check_file "{empty}"'],
                check=True,
                cwd=REPOSITORY_ROOT,
            )
            external = root / "external.json"
            external.write_text(
                '[{"type":"external-cloud-account"}]\n', encoding="utf-8"
            )
            subprocess.run(
                [
                    "bash",
                    "-c",
                    f'source "{SERVICE_MANAGER}"; qa_prerequisite_check_file "{external}"',
                ],
                check=True,
                cwd=REPOSITORY_ROOT,
            )

            bigquery = root / "bigquery.json"
            bigquery.write_text('[{"type":"google-bigquery"}]\n', encoding="utf-8")
            env = dict(os.environ)
            for name in ("GOOGLE_APPLICATION_CREDENTIALS", "BQ_TEST_PROJECT", "BQ_TEST_DATASET"):
                env.pop(name, None)
            result = subprocess.run(
                ["bash", "-c", f'set -o pipefail; source "{SERVICE_MANAGER}"; qa_prerequisite_check_file "{bigquery}"'],
                cwd=REPOSITORY_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("GOOGLE_APPLICATION_CREDENTIALS", result.stderr)

    def test_squid_service_preserves_upstream_directory_and_ipc_contract(self) -> None:
        script = SERVICE_MANAGER.read_text(encoding="utf-8")
        self.assertNotIn('mkdir -p "${QA_SERVICE_LOG_DIR}/${name}"', script)
        self.assertIn("sudo systemctl stop squid", script)
        self.assertIn("sudo rm -f /dev/shm/squid-*", script)
        self.assertIn('rm -rf "${log_dir}"', script)
        self.assertIn('--log_dir "${log_dir}"', script)

    def test_service_manager_rejects_unknown_runtime_service(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "services.json"
            manifest.write_text('[{"name":"bad","type":"unknown"}]\n', encoding="utf-8")
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    f'source "{SERVICE_MANAGER}"; qa_service_manager_init "{root}/runtime" "{root}" "{root}/logs"; qa_service_start_file "{manifest}"',
                ],
                cwd=REPOSITORY_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Unsupported service type", result.stderr)

    def test_mssql_patcher_removes_legacy_service_lifecycle(self) -> None:
        fixture = '''#!/usr/bin/env bash
DUCKDB_VERSION_DIRECTORY="v1.5.4"
cleanup() {
  if [[ "${MSSQL_COMPOSE_STARTED:-0}" == "1" ]]; then
    docker compose down
  fi
}
trap cleanup EXIT
python3 - <<'PYCODE'
config = {
    "skip_tests": [
        {"paths": ["legacy"]}
    ],
}
PYCODE
docker compose -f "${COMPOSE_FILE}" up -d sqlserver
export MSSQL_COMPOSE_STARTED=1
SQLSERVER_ID="$(docker compose -f "${COMPOSE_FILE}" ps -q sqlserver)"
if [[ -z "${SQLSERVER_ID}" ]]; then
  exit 1
fi
for _ in $(seq 1 60); do
  if docker exec "${SQLSERVER_ID}" true; then
    break
  fi
done
if ! docker exec "${SQLSERVER_ID}" true; then
  echo "SQL Server did not become ready" >&2
  exit 1
fi
echo continue
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.sh"
            destination = root / "destination.sh"
            source.write_text(fixture, encoding="utf-8")
            subprocess.run(
                [sys.executable, str(MSSQL_PATCHER), str(source), str(destination), "v1.5.4"],
                check=True,
                cwd=REPOSITORY_ROOT,
            )
            patched = destination.read_text(encoding="utf-8")
            self.assertNotIn("MSSQL_COMPOSE_STARTED", patched)
            self.assertNotIn('docker compose -f "${COMPOSE_FILE}" up', patched)
            self.assertIn('SQLSERVER_ID="${SQLSERVER_ID:?', patched)
            self.assertIn("echo continue", patched)
            self.assertNotIn('"skip_tests": [', patched)


if __name__ == "__main__":
    unittest.main()
