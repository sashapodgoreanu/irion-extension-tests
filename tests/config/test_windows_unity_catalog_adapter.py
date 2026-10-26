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

            def _reply(self, body, status=200):
                payload = json.dumps(body).encode()
""",
                encoding="utf-8",
            )

            adapter["patch_unity_catalog"](Path(directory))

            source = mock.read_text(encoding="utf-8")
            self.assertIn('os.environ.get("QA_NATIVE_WINDOWS") == "1" and body', source)
            self.assertIn("_qa_translate_file_uris(json.loads(body), windows=False)", source)
            self.assertIn('self.command == "POST"', source)
            self.assertIn('and "/staging-tables" in self.path', source)
            self.assertIn("absolute_unix_paths=not windows_staging", source)
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
                    "storage_location": "file:////mnt/d/a/qa/upstream/unity_catalog/data/nested_struct_pairs",
                    "nested": ["file:////mnt/d/a/qa/upstream/unity_catalog/data/timestamps"],
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
