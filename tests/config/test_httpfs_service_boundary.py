from __future__ import annotations

import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BATTERY_RUNNER = REPOSITORY_ROOT / "scripts" / "run-test-battery.sh"


class HttpfsServiceBoundaryTestCase(unittest.TestCase):
    def test_duckdb_runtime_is_exposed_before_battery_services_start(self) -> None:
        script = BATTERY_RUNNER.read_text(encoding="utf-8")
        self.assertIn('DUCKDB_BIN="${ARTIFACT_DIR}/bin/duckdb"', script)
        path_export = 'export PATH="$(cd "$(dirname "${DUCKDB_BIN}")" && pwd):${PATH}"'
        service_start = 'qa_service_start_file "${BATTERY_RUNTIME_CONFIG_DIR}/services.json"'
        self.assertIn(path_export, script)
        self.assertIn(service_start, script)
        self.assertLess(script.index(path_export), script.index(service_start))


if __name__ == "__main__":
    unittest.main()
