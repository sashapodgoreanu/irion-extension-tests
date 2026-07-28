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
PLAN_SCHEMA_PATH = REPOSITORY_ROOT / "schemas" / "execution-plan-v2.schema.json"
RESOLVER_PATH = REPOSITORY_ROOT / "scripts" / "resolve-extension-config.py"


class ExecutionPlanTestCase(unittest.TestCase):
    def test_plan_payload_is_valid_against_v2_schema(self) -> None:
        plan = resolve_config(load_config(CONFIG_PATH))
        schema = json.loads(PLAN_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(plan.payload()))
        self.assertEqual(errors, [])
        self.assertEqual(plan.payload()["schemaVersion"], 2)

    def test_matrix_is_derived_from_plan_profiles(self) -> None:
        plan = resolve_config(load_config(CONFIG_PATH))
        for case, matrix_case in zip(plan.cases, plan.matrix()["include"], strict=True):
            self.assertEqual(matrix_case["name"], case.name)
            self.assertEqual(matrix_case["profiles"], case.contract.payload()["profiles"])
            self.assertEqual(matrix_case["tests"], case.contract.profiles[0].tests)

    def test_plan_json_round_trip_preserves_payload(self) -> None:
        plan = resolve_config(load_config(CONFIG_PATH))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "execution-plan.json"
            plan.write_json(path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), plan.payload())

    def test_cli_persists_profile_plan_and_outputs_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "execution-plan.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(RESOLVER_PATH),
                    str(CONFIG_PATH),
                    "--plan-output",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
                cwd=REPOSITORY_ROOT,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["schemaVersion"], 2)
            self.assertEqual(
                [profile["name"] for profile in payload["cases"][0]["execution"]["profiles"]],
                ["sql", "autoload"],
            )
            outputs = dict(
                line.split("=", 1)
                for line in result.stdout.splitlines()
                if "=" in line
            )
            self.assertEqual(json.loads(outputs["matrix"])["include"][0]["name"], "httpfs")
            self.assertEqual(
                outputs["execution_plan_sha256"],
                resolve_config(load_config(CONFIG_PATH)).sha256(),
            )


if __name__ == "__main__":
    unittest.main()
