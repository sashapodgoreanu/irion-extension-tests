"""Verify that the MSSQL 0.3.0 Docker test fixture uses explicit TLS trust."""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run-mssql-tests-base.sh"
VARS = (
    "MSSQL_TEST_DSN",
    "MSSQL_TEST_URI",
    "MSSQL_TESTDB_DSN",
    "MSSQL_TESTDB_URI",
    "MSSQL_TEST_DSN_TLS",
    "MSSQL_TEST_SERVER",
    "MSSQL_TEST_CONNECTION_STRING",
)


def evaluate_test_connections(overrides: dict[str, str] | None = None) -> dict[str, str]:
    # Evaluate only the environment-default declarations; never start Docker or DuckDB.
    source = RUNNER.read_text(encoding="utf-8")
    declarations = [
        line for line in source.splitlines()
        if line.startswith("export MSSQL_TEST_")
    ]
    assert len(declarations) >= 12, "MSSQL test defaults were not found"
    commands = [
        "set -Eeuo pipefail",
        *declarations,
        *['printf "%s\\n" "${' + name + '}"' for name in VARS],
    ]
    process = subprocess.run(
        ["bash", "-c", "\n".join(commands)],
        env={"PATH": os.environ.get("PATH", ""), **(overrides or {})},
        text=True,
        capture_output=True,
        check=True,
    )
    return dict(zip(VARS, process.stdout.splitlines(), strict=True))


class MSSQLTLSDefaultsTest(unittest.TestCase):
    def test_local_sql_server_uses_explicit_certificate_trust(self) -> None:
        connections = evaluate_test_connections()
        self.assertIn("TrustServerCertificate=yes", connections["MSSQL_TEST_DSN"])
        self.assertIn("TrustServerCertificate=yes", connections["MSSQL_TESTDB_DSN"])
        self.assertIn("trustservercertificate=true", connections["MSSQL_TEST_URI"])
        self.assertIn("trustservercertificate=true", connections["MSSQL_TESTDB_URI"])
        self.assertIn("encrypt=true", connections["MSSQL_TEST_DSN_TLS"])
        self.assertIn("trustservercertificate=true", connections["MSSQL_TEST_DSN_TLS"])
        self.assertEqual(connections["MSSQL_TEST_SERVER"], connections["MSSQL_TEST_DSN"])
        self.assertEqual(connections["MSSQL_TEST_CONNECTION_STRING"], connections["MSSQL_TEST_DSN"])

    def test_explicit_connection_overrides_are_never_weakened(self) -> None:
        overrides = {
            "MSSQL_TEST_DSN": "Server=remote.example;TrustServerCertificate=no",
            "MSSQL_TESTDB_URI": "mssql://remote.example/db?trustservercertificate=false",
            "MSSQL_TEST_DSN_TLS": "mssql://remote.example/db?encrypt=true&trustservercertificate=false",
        }
        connections = evaluate_test_connections(overrides)
        for key, value in overrides.items():
            self.assertEqual(connections[key], value)
        self.assertEqual(connections["MSSQL_TEST_SERVER"], overrides["MSSQL_TEST_DSN"])
        self.assertEqual(
            connections["MSSQL_TEST_CONNECTION_STRING"], overrides["MSSQL_TEST_DSN"]
        )


if __name__ == "__main__":
    unittest.main()
