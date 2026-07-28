from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from qa import load_config, resolve_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPOSITORY_ROOT / "config" / "extensions.yml"
PLAN_SCHEMA_PATH = REPOSITORY_ROOT / "schemas" / "execution-plan-v1.schema.json"
RESOLVER_PATH = REPOSITORY_ROOT / "scripts" / "resolve-extension-config.py"


class ExecutionPlanTestCase(unittest.TestCase):
    def test_plan_is_versioned_and_matches_schema(self) -> None:
        plan = resolve_config(load_config(CONFIG_PATH))
        payload = plan.payload()
        schema = json.loads(PLAN_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(payload)

        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["runtime"]["duckdbVersion"], "v1.5.4")
        self.assertEqual(payload["runtime"]["ciToolsVersion"], "v1.5.4")
        self.assertEqual(payload["cases"][0]["name"], "httpfs")
        self.assertEqual(
            payload["cases"][0]["source"]["repository"], "duckdb/duckdb-httpfs"
        )
        self.assertEqual(payload["cases"][0]["execution"]["runner"], "standard")

    def test_matrix_is_derived_from_execution_plan(self) -> None:
        plan = resolve_config(load_config(CONFIG_PATH))
        matrix = plan.matrix()["include"]
        self.assertEqual(len(matrix), len(plan.payload()["cases"]))

        for case, matrix_item in zip(plan.payload()["cases"], matrix, strict=True):
            self.assertEqual(matrix_item["name"], case["name"])
            self.assertEqual(matrix_item["repository"], case["source"]["repository"])
            self.assertEqual(matrix_item["pin"], case["source"]["pin"])
            self.assertEqual(matrix_item["submodules"], case["source"]["submodules"])
            self.assertEqual(matrix_item["runner"], case["execution"]["runner"])
            self.assertEqual(matrix_item["setup"], case["execution"]["setup"])
            self.assertEqual(matrix_item["tests"], case["execution"]["tests"])
            self.assertEqual(matrix_item["extensions"], case["extensions"])
            self.assertEqual(matrix_item["ignoredTests"], case["ignoredTests"])

    def test_plan_can_be_written_and_round_tripped(self) -> None:
        plan = resolve_config(load_config(CONFIG_PATH))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "execution-plan.json"
            plan.write_json(path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), plan.payload())

    def test_resolver_persists_plan_and_preserves_actions_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "execution-plan.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(RESOLVER_PATH),
                    str(CONFIG_PATH),
                    "--plan-output",
                    str(output_path),
                ],
                check=True,
                text=True,
                capture_output=True,
            )
            outputs = dict(line.split("=", 1) for line in result.stdout.splitlines())
            plan = resolve_config(load_config(CONFIG_PATH))

            self.assertEqual(json.loads(outputs["matrix"]), plan.matrix())
            self.assertEqual(outputs["execution_plan_sha256"], plan.sha256())
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), plan.payload())


if __name__ == "__main__":
    unittest.main()
