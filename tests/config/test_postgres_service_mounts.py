from __future__ import annotations

import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SERVICE_MANAGER = REPOSITORY_ROOT / "scripts" / "service-manager.sh"


class PostgresServiceMountTestCase(unittest.TestCase):
    def test_postgres_service_shares_runner_fixture_paths(self) -> None:
        script = SERVICE_MANAGER.read_text(encoding="utf-8")
        self.assertIn(
            'battery_runtime_root="$(dirname "${QA_SERVICE_RUNTIME_ROOT}")"',
            script,
        )
        self.assertIn(
            '-v "${QA_SERVICE_UPSTREAM_ROOT}:${QA_SERVICE_UPSTREAM_ROOT}"',
            script,
        )
        self.assertIn(
            '-v "${battery_runtime_root}/tmp:${battery_runtime_root}/tmp"',
            script,
        )
        self.assertLess(
            script.index('-v "${QA_SERVICE_UPSTREAM_ROOT}:${QA_SERVICE_UPSTREAM_ROOT}"'),
            script.index('"postgres:${version}"'),
        )


if __name__ == "__main__":
    unittest.main()
