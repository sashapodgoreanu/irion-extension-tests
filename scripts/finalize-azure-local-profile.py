#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
AZURE_LOCAL_TESTS = ",".join(
    [
        "test/sql/http.test",
        "test/sql/azure.test",
        "test/sql/fs_logs.test",
        "test/sql/azure_glob.test",
        "test/sql/azure_etag.test",
        "test/sql/azure_writes.test",
        "test/sql/azure_secret.test",
        "test/sql/azure_vfs_ops.test",
        "test/sql/http_log_redaction.test",
        "test/sql/test_data_integrity.test",
        "test/sql/azure_scope_and_full_path.test",
    ]
)

config_path = ROOT / "config/extensions.yml"
config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
azure = config["testBatteries"]["azure"]
azurite = next(profile for profile in azure["profiles"] if profile["name"] == "azurite")
azurite["tests"] = AZURE_LOCAL_TESTS
config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

for relative in (
    "tests/config/test_config.py",
    "tests/config/test_phase5_finalization.py",
):
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    text = text.replace('"test/sql/*.test"', "AZURE_LOCAL_TESTS")
    if "AZURE_LOCAL_TESTS =" not in text:
        insertion = (
            "\nAZURE_LOCAL_TESTS = ",
            "\nAZURE_LOCAL_TESTS = " + repr(AZURE_LOCAL_TESTS) + "\n",
        )
        if relative.endswith("test_config.py"):
            marker = 'CONFIG_PATH = REPOSITORY_ROOT / "config" / "extensions.yml"\n'
        else:
            marker = 'ROOT = Path(__file__).resolve().parents[2]\n'
        text = text.replace(marker, marker + insertion[1], 1)
    path.write_text(text, encoding="utf-8")

from qa import load_config, resolve_config

plan = resolve_config(load_config(config_path))
matrix_hash = hashlib.sha256(
    json.dumps(plan.matrix(), separators=(",", ":")).encode("utf-8")
).hexdigest()
plan_hash = plan.sha256()

test_config_path = ROOT / "tests/config/test_config.py"
text = test_config_path.read_text(encoding="utf-8")
text = re.sub(
    r'EXPECTED_MATRIX_SHA256 = "[0-9a-f]{64}"',
    f'EXPECTED_MATRIX_SHA256 = "{matrix_hash}"',
    text,
    count=1,
)
text = re.sub(
    r'EXPECTED_PLAN_SHA256 = "[0-9a-f]{64}"',
    f'EXPECTED_PLAN_SHA256 = "{plan_hash}"',
    text,
    count=1,
)
test_config_path.write_text(text, encoding="utf-8")

Path(__file__).unlink()
