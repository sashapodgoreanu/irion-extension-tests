#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"expected text not found in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_configuration() -> None:
    path = ROOT / "config/extensions.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    azure = data["testBatteries"]["azure"]
    azure["services"] = [
        {"name": "storage-emulator", "type": "azurite", "port": 10000}
    ]
    azure["profiles"] = [
        {
            "name": "azurite",
            "tests": "test/sql/*.test",
            "services": [],
            "testConfig": {
                "kind": "generated",
                "description": "Azure local compatibility through Azurite",
                "excludedExtensions": [],
                "staticallyLoadedExtensions": ["core_functions", "parquet"],
            },
        },
        {
            "name": "proxy",
            "tests": "test/sql/proxy/*",
            "services": [
                {"name": "proxy", "type": "squid", "port": 3128},
                {
                    "name": "proxy-auth",
                    "type": "squid",
                    "port": 3129,
                    "auth": True,
                },
            ],
            "testConfig": {
                "kind": "generated",
                "description": "Azure proxy compatibility through local Squid services",
                "excludedExtensions": [],
                "staticallyLoadedExtensions": ["core_functions", "parquet"],
            },
        },
    ]

    unity = data["testBatteries"]["unity_catalog"]
    unity["pin"] = "dbca44d4dcc67c196af5fd910f0f26ce56d4930e"
    unity["services"] = [
        {
            "name": "unity-catalog-oss",
            "type": "unity-catalog-oss",
            "version": "1351641393665f5959b7b3d3c0c323a2b7e343c4",
            "port": 8080,
        }
    ]
    unity["profiles"] = [
        {
            "name": "oss",
            "tests": "test/sql/local_oss_unity_catalog/*",
            "services": [],
            "testConfig": {
                "kind": "generated",
                "description": "Unity Catalog compatibility against the local OSS server",
                "excludedExtensions": [],
                "staticallyLoadedExtensions": ["core_functions", "parquet"],
            },
        }
    ]

    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    policy = {
        "schemaVersion": 1,
        "defaults": {"minimumDiscovered": 1, "minimumExecuted": 1},
        "overrides": [
            {
                "case": "azure",
                "profile": "azurite",
                "minimumDiscovered": 11,
                "minimumExecuted": 11,
                "maximumSkipped": 0,
            },
            {
                "case": "azure",
                "profile": "proxy",
                "minimumDiscovered": 4,
                "minimumExecuted": 4,
                "maximumSkipped": 0,
            },
            {
                "case": "unity_catalog",
                "profile": "oss",
                "minimumDiscovered": 1,
                "minimumExecuted": 1,
                "maximumSkipped": 0,
            },
        ],
    }
    (ROOT / "config/result-policy.yml").write_text(
        yaml.safe_dump(policy, sort_keys=False), encoding="utf-8"
    )


def patch_schemas() -> None:
    for relative in (
        "schemas/extensions-v4.schema.json",
        "schemas/execution-plan-v4.schema.json",
    ):
        path = ROOT / relative
        schema = json.loads(path.read_text(encoding="utf-8"))
        defs = schema["$defs"]
        defs["squidService"]["properties"]["auth"] = {"type": "boolean"}
        defs["unityCatalogOssService"] = {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "type", "version", "port"],
            "properties": {
                "name": {"$ref": "#/$defs/serviceName"},
                "type": {"const": "unity-catalog-oss"},
                "version": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                "port": {"$ref": "#/$defs/port"},
            },
        }
        refs = defs["service"]["oneOf"]
        uc_ref = {"$ref": "#/$defs/unityCatalogOssService"}
        if uc_ref not in refs:
            azurite_index = refs.index({"$ref": "#/$defs/azuriteService"})
            refs.insert(azurite_index + 1, uc_ref)
        path.write_text(json.dumps(schema, separators=(",", ":")) + "\n", encoding="utf-8")


def patch_python_contracts() -> None:
    replace_once(
        "qa/config.py",
        '    {"python-http", "squid", "httpfs-minio", "azurite", "postgres", "sqlserver"}\n',
        '    {"python-http", "squid", "httpfs-minio", "azurite", "unity-catalog-oss", "postgres", "sqlserver"}\n',
    )
    replace_once(
        "qa/config.py",
        '    "azurite": ("azurite",),\n',
        '    "azurite": ("azurite",),\n    "unity-catalog-oss": ("unity-catalog-oss",),\n',
    )
    replace_once(
        "scripts/prepare-test-battery.py",
        '    "azurite",\n    "postgres",\n',
        '    "azurite",\n    "unity-catalog-oss",\n    "postgres",\n',
    )


def patch_service_manager() -> None:
    path = ROOT / "scripts/service-manager.sh"
    text = path.read_text(encoding="utf-8")

    old_fields = '''        item.get("database", "-"),
        item.get("username", "-"),
    ]
'''
    new_fields = '''        item.get("database", "-"),
        item.get("username", "-"),
        str(item.get("auth", False)).lower(),
    ]
'''
    if old_fields not in text:
        raise RuntimeError("service row field block not found")
    text = text.replace(old_fields, new_fields, 1)

    squid_pattern = re.compile(
        r"qa_service_start_squid\(\) \{.*?\n\}\n\nqa_service_start_httpfs_minio\(\)",
        re.S,
    )
    squid_replacement = '''qa_service_start_squid() {
  local name=$1
  local port=$2
  local auth=${3:-false}
  local script="${QA_SERVICE_UPSTREAM_ROOT}/scripts/run_squid.sh"
  if [[ ! -x "${script}" ]]; then
    echo "Squid service script is missing: ${script}" >&2
    return 1
  fi
  local log_dir="${QA_SERVICE_LOG_DIR}/${name}"
  local -a args=(--port "${port}" --log_dir "${log_dir}")
  if [[ "${auth}" == "true" ]]; then
    args+=(--auth)
  fi

  sudo systemctl stop squid >/dev/null 2>&1 \\
    || sudo service squid stop >/dev/null 2>&1 \\
    || true
  sudo rm -f /dev/shm/squid-* >/dev/null 2>&1 || true

  rm -rf "${log_dir}"
  (
    cd "${QA_SERVICE_UPSTREAM_ROOT}"
    ./scripts/run_squid.sh "${args[@]}"
  ) >"${QA_SERVICE_LOG_DIR}/${name}-process.log" 2>&1 &
  local pid=$!
  QA_SERVICE_CLEANUPS+=("pid|${name}|${pid}")
  qa_service_wait_for_port "${port}" "Squid service ${name}"
  export HTTP_PROXY_PUBLIC="127.0.0.1:${port}"
  export HTTP_PROXY_RUNNING=1
}

qa_service_start_httpfs_minio()'''
    text, count = squid_pattern.subn(squid_replacement, text, count=1)
    if count != 1:
        raise RuntimeError("unable to replace squid service implementation")

    azurite_tail = '''  (
    cd "${QA_SERVICE_UPSTREAM_ROOT}"
    ./scripts/upload_test_files_to_azurite.sh
  ) >>"${log}" 2>&1
}

qa_service_start_postgres() {
'''
    azurite_and_unity = '''  (
    cd "${QA_SERVICE_UPSTREAM_ROOT}"
    ./scripts/upload_test_files_to_azurite.sh
  ) >>"${log}" 2>&1

  local secret_name
  secret_name="qa_azure_$(printf '%s' "${QA_SERVICE_RUNTIME_ROOT}" | sha256sum | cut -c1-12)"
  duckdb -c "CREATE PERSISTENT SECRET ${secret_name} (TYPE AZURE, CONNECTION_STRING '${AZURE_STORAGE_CONNECTION_STRING}')" \\
    >>"${log}" 2>&1
  export ENABLE_DATA_INTEGRITY=1
  export DUCKDB_AZURE_PERSISTENT_SECRET_AVAILABLE=1
}

qa_service_start_unity_catalog_oss() {
  local name=$1
  local port=$2
  local version=$3
  local root="${QA_SERVICE_RUNTIME_ROOT}/${name}"
  local checkout="${root}/unitycatalog"
  local log="${QA_SERVICE_LOG_DIR}/${name}.log"

  if [[ "${port}" != "8080" ]]; then
    echo "The OSS Unity Catalog server currently requires port 8080" >&2
    return 1
  fi
  command -v java >/dev/null 2>&1 || {
    echo "Java is required for the OSS Unity Catalog server" >&2
    return 1
  }
  command -v git >/dev/null 2>&1 || {
    echo "Git is required for the OSS Unity Catalog server" >&2
    return 1
  }

  rm -rf "${root}"
  mkdir -p "${checkout}"
  git -C "${checkout}" init -q
  git -C "${checkout}" remote add origin https://github.com/unitycatalog/unitycatalog.git
  git -C "${checkout}" fetch --depth 1 origin "${version}" >>"${log}" 2>&1
  git -C "${checkout}" checkout --detach FETCH_HEAD >>"${log}" 2>&1
  local actual
  actual="$(git -C "${checkout}" rev-parse HEAD)"
  if [[ "${actual}" != "${version}" ]]; then
    echo "Unity Catalog server checkout must be ${version}; found ${actual}" >&2
    return 1
  fi

  (
    cd "${checkout}"
    ./build/sbt package
  ) >>"${log}" 2>&1

  (
    cd "${checkout}"
    exec setsid ./bin/start-uc-server
  ) >>"${log}" 2>&1 &
  local pid=$!
  QA_SERVICE_CLEANUPS+=("pgid|${name}|${pid}")
  qa_service_wait_for_port "${port}" "OSS Unity Catalog service ${name}" 180
  export UC_TEST_SERVER_RUNNING=1
  export UNITY_CATALOG_OSS_COMMIT="${actual}"
}

qa_service_start_postgres() {
'''
    if azurite_tail not in text:
        raise RuntimeError("azurite tail block not found")
    text = text.replace(azurite_tail, azurite_and_unity, 1)

    text = text.replace(
        "while IFS='|' read -r name service_type port version database username; do",
        "while IFS='|' read -r name service_type port version database username auth; do",
        1,
    )
    text = text.replace(
        '        qa_service_start_squid "${name}" "${port}"\n',
        '        qa_service_start_squid "${name}" "${port}" "${auth}"\n',
        1,
    )
    text = text.replace(
        '''      azurite)
        qa_service_start_azurite "${name}" "${port}"
        ;;
      postgres)
''',
        '''      azurite)
        qa_service_start_azurite "${name}" "${port}"
        ;;
      unity-catalog-oss)
        qa_service_start_unity_catalog_oss "${name}" "${port}" "${version}"
        ;;
      postgres)
''',
        1,
    )
    text = text.replace(
        '''      pid)
        if [[ -n "${value}" ]] && kill -0 "${value}" 2>/dev/null; then
          kill "${value}" || true
          wait "${value}" 2>/dev/null || true
        fi
        ;;
      httpfs-minio)
''',
        '''      pid)
        if [[ -n "${value}" ]] && kill -0 "${value}" 2>/dev/null; then
          kill "${value}" || true
          wait "${value}" 2>/dev/null || true
        fi
        ;;
      pgid)
        if [[ -n "${value}" ]]; then
          kill -TERM -- "-${value}" >/dev/null 2>&1 || true
          wait "${value}" 2>/dev/null || true
        fi
        ;;
      httpfs-minio)
''',
        1,
    )
    path.write_text(text, encoding="utf-8")


def patch_workflow() -> None:
    replace_once(
        ".github/workflows/extension-qa.yml",
        "        if: contains(matrix.capabilities, 'squid') || contains(matrix.capabilities, 'postgres-client') || contains(matrix.capabilities, 'azurite')\n",
        "        if: contains(matrix.capabilities, 'squid') || contains(matrix.capabilities, 'postgres-client') || contains(matrix.capabilities, 'azurite') || contains(matrix.capabilities, 'unity-catalog-oss')\n",
    )
    replace_once(
        ".github/workflows/extension-qa.yml",
        "          if [[ '${{ contains(matrix.capabilities, 'postgres-client') }}' == 'true' ]]; then\n            packages+=(postgresql-client)\n          fi\n",
        "          if [[ '${{ contains(matrix.capabilities, 'postgres-client') }}' == 'true' ]]; then\n            packages+=(postgresql-client)\n          fi\n          if [[ '${{ contains(matrix.capabilities, 'unity-catalog-oss') }}' == 'true' ]]; then\n            packages+=(openjdk-17-jdk-headless)\n          fi\n",
    )


def patch_tests_and_hashes() -> None:
    path = ROOT / "tests/config/test_config.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        '        self.assertEqual(azure["capabilities"], ["azurite"])\n        self.assertEqual(azure["prerequisites"], [])\n',
        '''        self.assertEqual(azure["capabilities"], ["azurite", "squid"])
        self.assertEqual(azure["prerequisites"], [])
        self.assertEqual([profile["name"] for profile in azure["profiles"]], ["azurite", "proxy"])
        self.assertEqual(azure["profiles"][0]["tests"], "test/sql/*.test")
        self.assertEqual(azure["profiles"][1]["tests"], "test/sql/proxy/*")
        self.assertEqual(azure["profiles"][1]["services"][1]["auth"], True)

        unity = next(case for case in matrix if case["name"] == "unity_catalog")
        self.assertEqual(unity["pin"], "dbca44d4dcc67c196af5fd910f0f26ce56d4930e")
        self.assertEqual(unity["services"][0]["type"], "unity-catalog-oss")
        self.assertEqual(unity["capabilities"], ["unity-catalog-oss"])
        self.assertEqual([profile["name"] for profile in unity["profiles"]], ["oss"])
''',
        1,
    )
    path.write_text(text, encoding="utf-8")

    validation_test = ROOT / "tests/config/test_phase5_finalization.py"
    validation_test.write_text(
        '''from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class Phase5FinalizationTest(unittest.TestCase):
    def test_azure_local_profiles_are_skip_free_by_policy(self) -> None:
        config = yaml.safe_load((ROOT / "config/extensions.yml").read_text(encoding="utf-8"))
        azure = config["testBatteries"]["azure"]
        self.assertEqual([p["name"] for p in azure["profiles"]], ["azurite", "proxy"])
        self.assertEqual(azure["profiles"][0]["tests"], "test/sql/*.test")
        self.assertEqual(azure["profiles"][1]["tests"], "test/sql/proxy/*")
        self.assertTrue(azure["profiles"][1]["services"][1]["auth"])

        policy = yaml.safe_load((ROOT / "config/result-policy.yml").read_text(encoding="utf-8"))
        overrides = {(item["case"], item["profile"]): item for item in policy["overrides"]}
        self.assertEqual(overrides[("azure", "azurite")]["maximumSkipped"], 0)
        self.assertEqual(overrides[("azure", "proxy")]["maximumSkipped"], 0)

    def test_unity_catalog_uses_pinned_oss_service(self) -> None:
        config = yaml.safe_load((ROOT / "config/extensions.yml").read_text(encoding="utf-8"))
        unity = config["testBatteries"]["unity_catalog"]
        self.assertEqual(unity["pin"], "dbca44d4dcc67c196af5fd910f0f26ce56d4930e")
        self.assertEqual(unity["profiles"][0]["tests"], "test/sql/local_oss_unity_catalog/*")
        self.assertEqual(unity["services"][0]["type"], "unity-catalog-oss")
        self.assertRegex(unity["services"][0]["version"], r"^[0-9a-f]{40}$")

        manager = (ROOT / "scripts/service-manager.sh").read_text(encoding="utf-8")
        self.assertIn("qa_service_start_unity_catalog_oss", manager)
        self.assertIn("export UC_TEST_SERVER_RUNNING=1", manager)
        self.assertIn("DUCKDB_AZURE_PERSISTENT_SECRET_AVAILABLE=1", manager)


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )

    from qa import load_config, resolve_config

    plan = resolve_config(load_config(ROOT / "config/extensions.yml"))
    matrix_hash = hashlib.sha256(
        json.dumps(plan.matrix(), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    plan_hash = plan.sha256()

    text = path.read_text(encoding="utf-8")
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
    path.write_text(text, encoding="utf-8")


def cleanup_bootstrap() -> None:
    for relative in (
        "scripts/phase5-finalize-repo.py",
        ".github/workflows/phase5-finalize.yml",
    ):
        path = ROOT / relative
        if path.exists():
            path.unlink()


def main() -> None:
    patch_configuration()
    patch_schemas()
    patch_python_contracts()
    patch_service_manager()
    patch_workflow()
    patch_tests_and_hashes()
    cleanup_bootstrap()


if __name__ == "__main__":
    main()
