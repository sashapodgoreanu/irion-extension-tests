from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from qa import load_config, resolve_config

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "extensions.yml"
DELTA_COMMIT = "45c40878601b54b4188b09e08732fe0d576ad222"


class DeltaLocalRuntimeTest(unittest.TestCase):
    def test_delta_local_runtime_follows_upstream_contracts(self) -> None:
        plan = resolve_config(load_config(CONFIG_PATH))
        matrix_case = next(
            item for item in plan.matrix()["include"] if item["name"] == "delta"
        )
        self.assertEqual(matrix_case["pin"], DELTA_COMMIT)
        self.assertEqual(matrix_case["prerequisites"], [])
        self.assertEqual([profile["name"] for profile in matrix_case["profiles"]], ["all"])

        runner = (ROOT / "scripts/run-standard-tests.sh").read_text(encoding="utf-8")
        preparer = (ROOT / "scripts/prepare-delta-local-tests.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('TEST_NAME}" == "delta"', runner)
        self.assertIn("prepare-delta-local-tests.sh", runner)
        self.assertIn("DELTA_MINIO_CONTAINER", runner)

        for upstream_contract in (
            "generate-data",
            "unpack-golden-tables-release",
            "DELTA_KERNEL_TESTS_PATH",
            "DAT_PATH",
            "GIT_REPOSITORY",
            "GIT_TAG",
            "scripts/env_minio",
            "scripts/create_minio_credential_file.sh",
            "scripts/upload_test_files_to_minio.sh",
        ):
            self.assertIn(upstream_contract, preparer)

        self.assertIn("cargo build --manifest-path", preparer)
        self.assertIn("GENERATED_DATA_AVAILABLE=1", preparer)
        self.assertIn("GOLDEN_TABLES_PATH", preparer)
        self.assertIn("DUCKDB_MINIO_TEST_SERVER_AVAILABLE=1", preparer)
        self.assertIn("raw.githubusercontent.com/duckdb/duckdb-httpfs", preparer)

        # Real cloud credentials remain intentionally outside the local profile.
        self.assertNotIn("export AZURE_CLIENT_ID", preparer)
        self.assertNotIn("export AZURE_CLIENT_SECRET", preparer)
        self.assertNotIn("export GENERATED_S3_DATA_AVAILABLE", preparer)

    def test_windows_delta_copy_dir_adapter_tracks_suite_growth(self) -> None:
        adapter = ROOT / "scripts/prepare-windows-test-source.py"
        makefile = """generate-data:
\t${PYTHON_BIN} scripts/data_generator/generate_test_data.py
\t# avoid footguns -- make outputs read only
\tfind data/generated -mindepth 1 -print0 | xargs -0 -n 1000 chmod a-w

unpack-golden-tables-release:
\t./scripts/unwrap_golden_tables.sh
"""
        test_bodies = {
            "test/sql/generated/basic.test": """require delta

statement ok
from copy_dir('data/generated/simple', '__TEST_DIR__/simple');
""",
            "test/sql/generated/future.test_slow": """require delta

query I
SELECT 1
----
1

statement ok
from copy_dir('data/generated/future', '__TEST_DIR__/future');
""",
        }

        with tempfile.TemporaryDirectory() as temporary:
            upstream = Path(temporary)
            (upstream / "Makefile").write_text(makefile, encoding="utf-8")
            for relative, body in test_bodies.items():
                path = upstream / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, str(adapter), "delta", str(upstream)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("copy_dir override for 2 SQLLogicTest file(s)", completed.stdout)

            for relative in test_bodies:
                patched = (upstream / relative).read_text(encoding="utf-8")
                self.assertEqual(
                    patched.count("# QA Windows Delta copy_dir compatibility"), 1
                )
                self.assertIn("CREATE OR REPLACE MACRO copy_dir", patched)
                self.assertIn(
                    "replace(dst_dir || filename[length(src_dir)+1:], chr(92), '/')",
                    patched,
                )
                self.assertLess(
                    patched.index("# QA Windows Delta copy_dir compatibility"),
                    patched.index("from copy_dir"),
                )

    def test_windows_delta_runner_uses_short_source_junction(self) -> None:
        windows_runner = (ROOT / "scripts/run-windows-wsl-battery.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("qa-delta-src", windows_runner)
        self.assertIn("New-Item -ItemType Junction", windows_runner)
        self.assertIn("$batterySourceLinux = Convert-ToWslPath $deltaSourceAlias", windows_runner)
        self.assertIn("$arguments.Add($batterySourceLinux)", windows_runner)
        self.assertIn("removed Delta short source alias", windows_runner)


if __name__ == "__main__":
    unittest.main()
