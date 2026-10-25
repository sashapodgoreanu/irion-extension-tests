"""Verify that the MSSQL 0.3.0 Docker test fixture uses explicit TLS trust."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run-mssql-tests-base.sh"
BASE_VARS = (
    "MSSQL_TEST_HOST",
    "MSSQL_TEST_PORT",
    "MSSQL_TEST_USER",
    "MSSQL_TEST_PASS",
    "MSSQL_TEST_DB",
)
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
    all_vars = set(BASE_VARS) | set(VARS)
    declarations = [
        line for line in source.splitlines()
        if line.startswith("export ") and line.partition("=")[0][7:] in all_vars
    ]
    declared_names = {line.partition("=")[0][7:] for line in declarations}
    assert declared_names == all_vars and len(declarations) == len(all_vars), (
        "MSSQL connection defaults or prerequisites missing or duplicated: "
        f"missing={sorted(all_vars - declared_names)}"
    )
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
    def test_seed_check_trusts_only_the_local_fixture_certificate(self) -> None:
        script = RUNNER.read_text(encoding="utf-8")
        self.assertIn("CREATE SECRET qa_mssql_seedcheck", script)
        self.assertIn("trust_server_certificate true", script)
        self.assertIn("ATTACH '' AS seedcheck (TYPE mssql, SECRET qa_mssql_seedcheck)", script)
        self.assertNotIn('"--unsigned"', script)
        self.assertIn("  --keep-home", script)
        self.assertIn('if row.get("installed_from", "").lower() != "community":', script)
        self.assertNotIn('rm -f "${MSSQL_EXTENSION_PATH}"', script)

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


    def test_signed_requirement_adapter_preserves_upstream_statements(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        marker = 'mssql-require-adaptation.json" <<\x27PY\x27'
        self.assertIn(marker, source)
        code = source.split(marker, 1)[1].split("\nPY\n", 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "test" / "sql"
            folder.mkdir(parents=True)
            original = (
                "# require mssql is documented here\n"
                "require mssql\n"
                "require-env MSSQL_TEST_DSN\n"
                "statement ok\nSELECT 42;\n"
            )
            target = folder / "sample.test"
            target.write_text(original, encoding="utf-8")
            report = root / "report.json"
            result = subprocess.run(
                [sys.executable, "-c", code, str(root), str(report)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                original.replace(
                    "\nrequire mssql\n",
                    "\nrequire-env MSSQL_QA_SIGNED_EXTENSION_AVAILABLE 1\n",
                ),
            )
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(payload["signed_community_probe_required"])
            self.assertEqual(payload["directives_changed"], 1)
            self.assertEqual(payload["changes"][0]["path"], "test/sql/sample.test")
            self.assertNotEqual(
                payload["changes"][0]["original_sha256"],
                payload["changes"][0]["adapted_sha256"],
            )

    def test_mssql_gate_remains_signature_protected(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        first = source.index('print("Dynamic MSSQL community-signed LOAD probe passed")')
        adapter = source.index("mssql-require-adaptation.json")
        active = source.index("export MSSQL_QA_SIGNED_EXTENSION_AVAILABLE=1")
        self.assertLess(first, adapter)
        self.assertLess(adapter, active)
        self.assertIn("MSSQL_TEST_INIT_SCRIPT", source)
        self.assertIn("^require-env MSSQL_QA_SIGNED_EXTENSION_AVAILABLE:", source)
        self.assertIn("No require mssql directives", source)
        self.assertNotIn("allow_unsigned_extensions=true", source)



if __name__ == "__main__":
    unittest.main()
