from __future__ import annotations

import ast
import json
import re
import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class WindowsUnityCatalogAdapterTest(unittest.TestCase):
    def test_live_server_proxy_rewrites_wsl_file_uris_both_directions(self) -> None:
        proxy = runpy.run_path(str(ROOT / "scripts" / "unity-catalog-windows-proxy.py"))
        server_tmp_dir = "/tmp/qa-unity.abc"
        mirror_dir = "/mnt/d/a/qa/.qa-unity.abc/unity-catalog-server-data"
        mirror_uri = "file:///a/qa/.qa-unity.abc/unity-catalog-server-data"
        payload = (
            b'{"storage_location":"file:///tmp/qa-unity.abc/ducktest-uc-data-one/tables/a",'
            b'"nested":[{"uri":"file:///tmp/qa-unity.abc/ducktest-uc-data-one/tables/b"}]}'
        )
        windows = proxy["rewrite_json_payload"](
            payload,
            to_windows=True,
            server_tmp_dir=server_tmp_dir,
            mirror_dir=mirror_dir,
            mirror_uri=mirror_uri,
        )
        self.assertEqual(
            json.loads(windows),
            {
                "storage_location": "file:///a/qa/.qa-unity.abc/unity-catalog-server-data/ducktest-uc-data-one/tables/a",
                "nested": [{"uri": "file:///a/qa/.qa-unity.abc/unity-catalog-server-data/ducktest-uc-data-one/tables/b"}],
            },
        )
        wsl = proxy["rewrite_json_payload"](
            windows,
            to_windows=False,
            server_tmp_dir=server_tmp_dir,
            mirror_dir=mirror_dir,
            mirror_uri=mirror_uri,
        )
        self.assertEqual(
            json.loads(wsl),
            {
                "storage_location": "file:///tmp/qa-unity.abc/ducktest-uc-data-one/tables/a",
                "nested": [{"uri": "file:///tmp/qa-unity.abc/ducktest-uc-data-one/tables/b"}],
            },
        )

    def test_proxy_mirror_copies_new_server_files_without_overwriting_windows_files(self) -> None:
        proxy = runpy.run_path(str(ROOT / "scripts" / "unity-catalog-windows-proxy.py"))
        handler = proxy["UnityCatalogProxy"]
        with tempfile.TemporaryDirectory() as directory:
            server_tmp_dir = Path(directory) / "server-tmp"
            mirror_dir = Path(directory) / "windows-mirror"
            server_table = server_tmp_dir / "ducktest-uc-data-one" / "duck" / "cmt" / "_delta_log"
            server_table.mkdir(parents=True)
            source_file = server_table / "00000000000000000000.json"
            source_file.write_text("server-created", encoding="utf-8")

            handler.server_tmp_dir = str(server_tmp_dir)
            handler.mirror_dir = str(mirror_dir)
            handler._copy_missing_server_files()
            mirror_file = mirror_dir / "ducktest-uc-data-one" / "duck" / "cmt" / "_delta_log" / source_file.name
            self.assertEqual(mirror_file.read_text(encoding="utf-8"), "server-created")

            mirror_file.write_text("windows-updated", encoding="utf-8")
            source_file.write_text("new-server-version", encoding="utf-8")
            handler._copy_missing_server_files()
            self.assertEqual(mirror_file.read_text(encoding="utf-8"), "windows-updated")
            handler.server_tmp_dir = ""
            handler.mirror_dir = ""

    def test_wsl_data_drive_is_mapped_and_checked_bidirectionally(self) -> None:
        setup = (ROOT / "scripts" / "setup-windows-wsl-runtime.ps1").read_text(encoding="utf-8")
        self.assertIn("net.exe use W: $wslShare /persistent:no", setup)
        self.assertIn("Test-Path -LiteralPath $wslProbeFile", setup)
        self.assertIn("[System.IO.File]::WriteAllText", setup)
        self.assertIn('test -f "/tmp/$wslProbe/from-windows"', setup)

    def test_live_server_data_uses_a_local_ntfs_mirror(self) -> None:
        runner = (ROOT / "scripts" / "run-unity-catalog-pytest.sh").read_text(encoding="utf-8")
        self.assertIn('QA_WINDOWS_UC_SERVER_TMP_DIR="${WINDOWS_TMP_DIR}"', runner)
        self.assertIn('QA_WINDOWS_UC_SERVER_MIRROR_DIR="${WINDOWS_UC_SERVER_MIRROR_DIR}"', runner)
        self.assertIn('--server-tmp-dir "${QA_WINDOWS_UC_SERVER_TMP_DIR}"', runner)
        self.assertIn('--mirror-dir "${QA_WINDOWS_UC_SERVER_MIRROR_DIR}"', runner)
        self.assertIn('--mirror-uri "${QA_WINDOWS_UC_SERVER_MIRROR_URI}"', runner)

    def test_mirror_uri_does_not_repeat_the_windows_drive(self) -> None:
        uri = runpy.run_path(str(ROOT / "scripts" / "windows-file-uri.py"))[
            "current_drive_rooted_file_uri"
        ](r"D:\a\qa\.qa-unity.abc\unity-catalog-server-data")
        self.assertEqual(uri, "file:///a/qa/.qa-unity.abc/unity-catalog-server-data")
        self.assertNotRegex(uri, r"^file:///[A-Za-z]:/")

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
            server = Path(directory) / "test" / "py" / "uc" / "server.py"
            server.write_text(
                'PORT = int(os.environ.get("DUCKTEST_UC_PORT", "8080"))\n'
                'env = {\n        "DUCKTEST_UC_PORT": str(PORT),\n    }\n',
                encoding="utf-8",
            )

            adapter["patch_unity_catalog"](Path(directory))

            source = mock.read_text(encoding="utf-8")
            irc_source = irc_mock.read_text(encoding="utf-8")
            oss_source = oss.read_text(encoding="utf-8")
            server_source = server.read_text(encoding="utf-8")
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
            self.assertIn('DUCKTEST_UC_PROXY_PORT', server_source)
            self.assertIn('DUCKTEST_UC_SERVER_PORT', server_source)
            self.assertIn('"DUCKTEST_UC_PORT": str(SERVER_PORT)', server_source)
            ast.parse(server_source)
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
                "nested": [
                    "file:///mnt/d/a/qa/upstream/unity_catalog/data/timestamps",
                    "file:///tmp/qa-unity.abc12345/ducktest-uc-data/tables/abc",
                ],
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
                    "nested": [
                        "file:/D:/a/qa/upstream/unity_catalog/data/timestamps",
                        "file:///W:/tmp/qa-unity.abc12345/ducktest-uc-data/tables/abc",
                    ],
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
