#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def write(relative: str, content: str) -> None:
    (ROOT / relative).write_text(content, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def replace_in_section(
    text: str,
    start: str,
    end: str,
    old: str,
    new: str,
    label: str,
) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index + len(start))
    section = text[start_index:end_index]
    section = replace_once(section, old, new, label)
    return text[:start_index] + section + text[end_index:]


# Configuration: only BigQuery and Iceberg declare the external-account contract.
config_path = "config/extensions.yml"
config = read(config_path)
config = replace_in_section(
    config,
    "\n  iceberg:\n",
    "\n  azure:\n",
    "    prerequisites: []",
    "    prerequisites:\n      - type: external-cloud-account",
    "iceberg prerequisite",
)
config = replace_in_section(
    config,
    "\n  bigquery:\n",
    "\n  mssql:\n",
    "    prerequisites:\n      - type: google-bigquery",
    "    prerequisites:\n      - type: google-bigquery\n      - type: external-cloud-account",
    "bigquery prerequisite",
)
write(config_path, config)

# Typed prerequisite -> capability compilation.
config_py_path = "qa/config.py"
config_py = read(config_py_path)
config_py = replace_once(
    config_py,
    'VALID_PREREQUISITE_TYPES = frozenset({"google-bigquery"})',
    'VALID_PREREQUISITE_TYPES = frozenset(\n    {"google-bigquery", "external-cloud-account"}\n)',
    "valid prerequisite types",
)
config_py = replace_once(
    config_py,
    'PREREQUISITE_CAPABILITIES: dict[str, tuple[str, ...]] = {\n    "google-bigquery": ("google-cloud-auth",),\n}',
    'PREREQUISITE_CAPABILITIES: dict[str, tuple[str, ...]] = {\n    "google-bigquery": ("google-cloud-auth",),\n    "external-cloud-account": ("accepted-failure",),\n}',
    "prerequisite capabilities",
)
write(config_py_path, config_py)

# Strict schemas.
config_schema_path = ROOT / "schemas/extensions-v3.schema.json"
config_schema = json.loads(config_schema_path.read_text(encoding="utf-8"))
config_schema["$defs"]["prerequisite"]["properties"]["type"]["enum"] = [
    "google-bigquery",
    "external-cloud-account",
]
config_schema_path.write_text(json.dumps(config_schema, indent=2) + "\n", encoding="utf-8")

plan_schema_path = ROOT / "schemas/execution-plan-v3.schema.json"
plan_schema = json.loads(plan_schema_path.read_text(encoding="utf-8"))
plan_schema["$defs"]["prerequisite"]["properties"]["type"]["enum"] = [
    "google-bigquery",
    "external-cloud-account",
]
capabilities = plan_schema["$defs"]["case"]["properties"]["execution"]["properties"][
    "capabilities"
]["items"]["enum"]
if "accepted-failure" not in capabilities:
    capabilities.append("accepted-failure")
plan_schema_path.write_text(json.dumps(plan_schema, indent=2) + "\n", encoding="utf-8")

# Runtime prerequisite manager: the external account marker is metadata only.
manager_path = "scripts/service-manager.sh"
manager = read(manager_path)
manager = replace_once(
    manager,
    """        ;;\n      *)\n        echo \"Unsupported prerequisite: ${prerequisite}\" >&2""",
    """        ;;\n      external-cloud-account)\n        # Metadata-only prerequisite: CI may accept this battery's failure.\n        ;;\n      *)\n        echo \"Unsupported prerequisite: ${prerequisite}\" >&2""",
    "external account prerequisite handler",
)
write(manager_path, manager)

# GitHub Actions: only cases with the compiled capability may fail softly.
workflow_path = ".github/workflows/extension-qa.yml"
workflow = read(workflow_path)
workflow = replace_once(
    workflow,
    "    timeout-minutes: 120\n    strategy:",
    "    timeout-minutes: 120\n    continue-on-error: ${{ contains(matrix.capabilities, 'accepted-failure') }}\n    strategy:",
    "continue-on-error contract",
)
workflow = replace_once(
    workflow,
    "      - name: Validate Google BigQuery credentials\n",
    """      - name: Report accepted external-account failure\n        if: contains(matrix.capabilities, 'accepted-failure')\n        run: echo \"Accepted failure contract — required external cloud account is unavailable\"\n\n      - name: Validate Google BigQuery credentials\n""",
    "accepted failure report step",
)
write(workflow_path, workflow)

# Regression contracts.
test_config_path = "tests/config/test_config.py"
test_config = read(test_config_path)
test_config = replace_once(
    test_config,
    'self.assertEqual(bigquery["prerequisites"], [{"type": "google-bigquery"}])\n        self.assertEqual(bigquery["capabilities"], ["google-cloud-auth"])',
    'self.assertEqual(\n            bigquery["prerequisites"],\n            [\n                {"type": "google-bigquery"},\n                {"type": "external-cloud-account"},\n            ],\n        )\n        self.assertEqual(\n            bigquery["capabilities"], ["google-cloud-auth", "accepted-failure"]\n        )\n\n        iceberg = next(case for case in matrix if case["name"] == "iceberg")\n        self.assertEqual(\n            iceberg["prerequisites"], [{"type": "external-cloud-account"}]\n        )\n        self.assertEqual(iceberg["capabilities"], ["accepted-failure"])\n        self.assertEqual(\n            [\n                case["name"]\n                for case in matrix\n                if "accepted-failure" in case["capabilities"]\n            ],\n            ["iceberg", "bigquery"],\n        )',
    "config accepted failures assertions",
)
write(test_config_path, test_config)

test_runtime_path = "tests/config/test_profiles_runtime.py"
test_runtime = read(test_runtime_path)
test_runtime = replace_once(
    test_runtime,
    'json.loads((runtime / "prerequisites.json").read_text(encoding="utf-8")),\n                [{"type": "google-bigquery"}],',
    'json.loads((runtime / "prerequisites.json").read_text(encoding="utf-8")),\n                [\n                    {"type": "google-bigquery"},\n                    {"type": "external-cloud-account"},\n                ],',
    "runtime BigQuery prerequisites",
)
test_runtime = replace_once(
    test_runtime,
    'json.loads((runtime / "capabilities.json").read_text(encoding="utf-8")),\n                ["google-cloud-auth"],',
    'json.loads((runtime / "capabilities.json").read_text(encoding="utf-8")),\n                ["google-cloud-auth", "accepted-failure"],',
    "runtime BigQuery capabilities",
)
test_runtime = replace_once(
    test_runtime,
    'self.assertIn("uses: google-github-actions/auth@v3", workflow)\n        self.assertNotIn("action-setup-postgres", workflow)',
    'self.assertIn("uses: google-github-actions/auth@v3", workflow)\n        self.assertIn(\n            "continue-on-error: ${{ contains(matrix.capabilities, \'accepted-failure\') }}",\n            workflow,\n        )\n        self.assertNotIn("action-setup-postgres", workflow)',
    "workflow accepted failure assertion",
)
test_runtime = replace_once(
    test_runtime,
    '            bigquery = root / "bigquery.json"',
    '            external = root / "external.json"\n            external.write_text(\n                \'[{"type":"external-cloud-account"}]\\n\', encoding="utf-8"\n            )\n            subprocess.run(\n                [\n                    "bash",\n                    "-c",\n                    f\'source "{SERVICE_MANAGER}"; qa_prerequisite_check_file "{external}"\',\n                ],\n                check=True,\n                cwd=REPOSITORY_ROOT,\n            )\n\n            bigquery = root / "bigquery.json"',
    "external prerequisite runtime test",
)
write(test_runtime_path, test_runtime)

# Recompute canonical golden hashes after the contract changes.
from qa import load_config, resolve_config  # noqa: E402

plan = resolve_config(load_config(ROOT / "config/extensions.yml"))
compact_matrix = json.dumps(plan.matrix(), separators=(",", ":"))
matrix_hash = hashlib.sha256(compact_matrix.encode("utf-8")).hexdigest()
plan_hash = plan.sha256()

test_config = read(test_config_path)
test_config = re.sub(
    r'EXPECTED_MATRIX_SHA256 = "[0-9a-f]+"',
    f'EXPECTED_MATRIX_SHA256 = "{matrix_hash}"',
    test_config,
    count=1,
)
test_config = re.sub(
    r'EXPECTED_PLAN_SHA256 = "[0-9a-f]+"',
    f'EXPECTED_PLAN_SHA256 = "{plan_hash}"',
    test_config,
    count=1,
)
write(test_config_path, test_config)

# Remove one-time migration inputs from the resulting commit.
(ROOT / "scripts/apply-accepted-cloud-failures.py").unlink()
(ROOT / ".github/workflows/apply-accepted-cloud-failures.yml").unlink()

print(f"matrix_sha256={matrix_hash}")
print(f"plan_sha256={plan_hash}")
