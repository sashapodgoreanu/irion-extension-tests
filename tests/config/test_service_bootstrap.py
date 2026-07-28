from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BATTERY_RUNNER = REPOSITORY_ROOT / "scripts" / "run-test-battery.sh"


class ServiceBootstrapTestCase(unittest.TestCase):
    def test_duckdb_runtime_is_available_before_services_start(self) -> None:
        script = BATTERY_RUNNER.read_text(encoding="utf-8")

        runtime_assignment = 'DUCKDB_BIN="${ARTIFACT_DIR}/bin/duckdb"'
        path_export = 'export PATH="$(cd "$(dirname "${DUCKDB_BIN}")" && pwd):${PATH}"'
        service_start = (
            'qa_service_start_file '
            '"${BATTERY_RUNTIME_CONFIG_DIR}/services.json"'
        )

        self.assertIn(runtime_assignment, script)
        self.assertIn('if [[ ! -x "${DUCKDB_BIN}" ]]', script)
        self.assertIn(path_export, script)
        self.assertIn(service_start, script)
        self.assertLess(script.index(path_export), script.index(service_start))


if __name__ == "__main__":
    unittest.main()
