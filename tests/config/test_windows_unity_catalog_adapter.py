from __future__ import annotations

import ast
import re
import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class WindowsUnityCatalogAdapterTest(unittest.TestCase):
    def test_mock_catalog_translates_file_uris_both_directions(self) -> None:
        adapter = runpy.run_path(str(ROOT / "scripts" / "prepare-windows-test-source.py"))
        with tempfile.TemporaryDirectory() as directory:
            mock = Path(directory) / "test" / "py" / "uc" / "mock.py"
            mock.parent.mkdir(parents=True)
            mock.write_text(
                """import http.server
import json
import re
import subprocess
import threading
from pathlib import Path

CATALOG = "duck"

_REPO = Path(__file__).resolve().parents[3]

class MockUnityCatalog:
    def __init__(self):
        class Handler:
            def _respond(self, method, body):
                answer = respond(method, self.path, body)
                status, payload = answer
                self._reply(payload, status)
                return answer

            def do_POST(self):
                if plan is None:
                    self.send_error(404)
                    return
                self._reply(plan(self.path))

            def _reply(self, body, status=200):
                payload = json.dumps(body).encode()
""",
                encoding="utf-8",
            )
            irc_mock = Path(directory) / "test" / "irc" / "test_irc_scan_plan_mock.py"
            irc_mock.parent.mkdir(parents=True)
            irc_mock.write_text(
                """import http.server
import json
import subprocess

class Handler:
    def _dispatch(self, method):
        path = self.path
        if "/api/2.1/unity-catalog/tables" in path:
            payload = {"tables": []}
        else:
            # IRC scan-plan routes -- delegated to the per-test script.
            payload = self.server.plan_script(method, path, self.server.requests)

class MockUC:
    def serve_delta_table(self, location, columns):
        self._httpd.table_info["storage_location"] = f"file://{location}"
        self._httpd.table_info["columns"] = columns
""",
                encoding="utf-8",
            )
            oss = Path(directory) / "test" / "py" / "uc" / "oss.py"
            oss.write_text(
                "def inspect_fixture():\n"
                "    def instantiate():\n"
                "        try:\n"
                "            table = canonicalize(duckdb_bin, definition)\n"
                "        except Exception:\n"
                "            pass\n",
                encoding="utf-8",
            )

            adapter["patch_unity_catalog"](Path(directory))

            source = mock.read_text(encoding="utf-8")
            irc_source = irc_mock.read_text(encoding="utf-8")
            oss_source = oss.read_text(encoding="utf-8")
            self.assertIn('os.environ.get("QA_NATIVE_WINDOWS") == "1" and body', source)
            self.assertIn("_qa_translate_file_uris(json.loads(body), windows=False)", source)
            self.assertIn('self.command == "POST"', source)
            self.assertIn('and "/staging-tables" in self.path', source)
            self.assertIn("absolute_unix_paths=not windows_staging", source)
            self.assertIn("/temporary-table-credentials", source)
            self.assertIn('os.environ.get("QA_NATIVE_WINDOWS") == "1"', irc_source)
            self.assertIn('r"(?i)^file:///mnt/([a-z])/"', irc_source)
            self.assertIn('"file:/" + match.group(1).upper() + ":/"', irc_source)
            self.assertIn("/temporary-table-credentials", irc_source)
            self.assertIn('workdir=os.environ.get("QA_WINDOWS_TEMP_DIR")', oss_source)
            ast.parse(oss_source)
            module = ast.parse(source)
            helper = next(
                node
                for node in module.body
                if isinstance(node, ast.FunctionDef) and node.name == "_qa_translate_file_uris"
            )
            scope = {"re": re}
            exec(compile(ast.Module(body=[helper], type_ignores=[]), "<adapter-test>", "exec"), scope)
            translate = scope["_qa_translate_file_uris"]

            wsl_payload = {
                "storage_location": "file:///mnt/d/a/qa/.qa-unity/table",
                "nested": ["file:///mnt/c/tmp/fixture"],
            }
            windows_payload = translate(wsl_payload, windows=True)
            self.assertEqual(
                windows_payload,
                {
                    "storage_location": "file:///D:/a/qa/.qa-unity/table",
                    "nested": ["file:///C:/tmp/fixture"],
                },
            )
            self.assertEqual(translate(windows_payload, windows=False), wsl_payload)

            wsl_external_payload = {
                "storage_location": "file:///mnt/d/a/qa/upstream/unity_catalog/data/nested_struct_pairs",
                "nested": ["file:///mnt/d/a/qa/upstream/unity_catalog/data/timestamps"],
            }
            windows_external_payload = translate(
                wsl_external_payload,
                windows=True,
                absolute_unix_paths=True,
            )
            self.assertEqual(
                windows_external_payload,
                {
                    "storage_location": "file:/D:/a/qa/upstream/unity_catalog/data/nested_struct_pairs",
                    "nested": ["file:/D:/a/qa/upstream/unity_catalog/data/timestamps"],
                },
            )
            self.assertEqual(translate(windows_external_payload, windows=False), wsl_external_payload)
            self.assertEqual(adapter["PATCHERS"]["unity_catalog"], adapter["patch_unity_catalog"])

    def test_upstream_mock_drift_fails_closed(self) -> None:
        adapter = runpy.run_path(str(ROOT / "scripts" / "prepare-windows-test-source.py"))
        with tempfile.TemporaryDirectory() as directory:
            mock = Path(directory) / "test" / "py" / "uc" / "mock.py"
            mock.parent.mkdir(parents=True)
            mock.write_text("import json\n", encoding="utf-8")

            with self.assertRaises(adapter["PatchError"]):
                adapter["patch_unity_catalog"](Path(directory))


if __name__ == "__main__":
    unittest.main()
