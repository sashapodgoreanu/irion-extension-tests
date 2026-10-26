#!/usr/bin/env python3
"""Bridge Unity Catalog file URIs between native Windows and its WSL server."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit


FILE_URI = "file:///"


def translate_value(
    value: Any,
    *,
    to_windows: bool,
    server_tmp_dir: str = "",
    mirror_dir: str = "",
    mirror_uri: str = "",
) -> Any:
    if isinstance(value, str):
        if to_windows and server_tmp_dir and mirror_uri and value.lower().startswith(FILE_URI):
            uri_path = unquote(urlsplit(value).path)
            try:
                relative = Path(uri_path).relative_to(Path(server_tmp_dir))
            except ValueError:
                relative = None
            if relative and relative.parts and relative.parts[0].startswith("ducktest-uc-data-"):
                return mirror_uri.rstrip("/") + "/" + quote(relative.as_posix(), safe="/")
        elif not to_windows and mirror_dir and mirror_uri and value.lower().startswith(
            mirror_uri.rstrip("/").lower() + "/"
        ):
            prefix = mirror_uri.rstrip("/") + "/"
            relative = unquote(value[len(prefix) :])
            if relative.split("/", 1)[0].startswith("ducktest-uc-data-"):
                return "file://" + server_tmp_dir.rstrip("/") + "/" + quote(relative, safe="/")
        return value
    if isinstance(value, list):
        return [
            translate_value(
                item,
                to_windows=to_windows,
                server_tmp_dir=server_tmp_dir,
                mirror_dir=mirror_dir,
                mirror_uri=mirror_uri,
            )
            for item in value
        ]
    if isinstance(value, dict):
        return {
            key: translate_value(
                item,
                to_windows=to_windows,
                server_tmp_dir=server_tmp_dir,
                mirror_dir=mirror_dir,
                mirror_uri=mirror_uri,
            )
            for key, item in value.items()
        }
    return value


def rewrite_json_payload(
    payload: bytes,
    *,
    to_windows: bool,
    server_tmp_dir: str = "",
    mirror_dir: str = "",
    mirror_uri: str = "",
) -> bytes:
    """Translate file URIs recursively in a JSON request or response body."""
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return payload
    return json.dumps(
        translate_value(
            value,
            to_windows=to_windows,
            server_tmp_dir=server_tmp_dir,
            mirror_dir=mirror_dir,
            mirror_uri=mirror_uri,
        ),
        separators=(",", ":"),
    ).encode()


class UnityCatalogProxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    target_host = "127.0.0.1"
    target_port = 8081
    server_tmp_dir = ""
    mirror_dir = ""
    mirror_uri = ""
    mirror_lock = threading.Lock()

    @classmethod
    def _server_storage_paths(cls, payload: bytes) -> set[Path]:
        """Find server-owned storage paths in a UC JSON response."""
        if not cls.server_tmp_dir:
            return set()
        try:
            value = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return set()

        server_tmp = Path(cls.server_tmp_dir)
        paths: set[Path] = set()

        def visit(item: Any) -> None:
            if isinstance(item, str) and item.lower().startswith("file://"):
                uri_path = unquote(urlsplit(item).path)
                source = Path(uri_path)
                try:
                    relative = source.relative_to(server_tmp)
                except ValueError:
                    return
                if relative.parts and relative.parts[0].startswith("ducktest-uc-data-"):
                    paths.add(source)
            elif isinstance(item, list):
                for child in item:
                    visit(child)
            elif isinstance(item, dict):
                for child in item.values():
                    visit(child)

        visit(value)
        return paths

    @classmethod
    def _copy_missing_server_files(cls, source_paths: set[Path]) -> None:
        """Copy only referenced UC storage trees to NTFS for native Windows DuckDB."""
        if not cls.server_tmp_dir or not cls.mirror_dir:
            return
        server_tmp = Path(cls.server_tmp_dir)
        mirror_root = Path(cls.mirror_dir)
        if not server_tmp.is_dir():
            return

        copied_files = 0
        with cls.mirror_lock:
            for source_path in source_paths:
                try:
                    relative_path = source_path.relative_to(server_tmp)
                except ValueError:
                    continue
                if not relative_path.parts or not relative_path.parts[0].startswith("ducktest-uc-data-"):
                    continue
                if source_path.is_file():
                    source_files = [source_path]
                    source_root = source_path.parent
                elif source_path.is_dir():
                    source_root = source_path
                    source_files = []
                    for current, _, files in os.walk(source_root):
                        source_files.extend(Path(current) / filename for filename in files)
                else:
                    continue

                destination_root = mirror_root / source_root.relative_to(server_tmp)
                for source_file in source_files:
                    destination_file = destination_root / source_file.relative_to(source_root)
                    if not destination_file.exists():
                        destination_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source_file, destination_file)
                        copied_files += 1
        if copied_files:
            print(f"Mirrored {copied_files} new Unity Catalog server file(s) onto NTFS", flush=True)

    def _forward(self) -> None:
        if self.path == "/__qa_proxy_health__":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", "2")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(b"ok")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length) if content_length else b""
        headers = {
            name: value
            for name, value in self.headers.items()
            if name.lower() not in {"connection", "content-length", "host", "transfer-encoding"}
        }
        # Avoid compressed payloads so URI translation can remain content-aware.
        headers["Accept-Encoding"] = "identity"
        if body and "json" in self.headers.get("Content-Type", "").lower():
            body = rewrite_json_payload(
                body,
                to_windows=False,
                server_tmp_dir=self.server_tmp_dir,
                mirror_dir=self.mirror_dir,
                mirror_uri=self.mirror_uri,
            )

        connection = http.client.HTTPConnection(self.target_host, self.target_port, timeout=60)
        try:
            connection.request(self.command, self.path, body=body or None, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
            response_headers = response.getheaders()
            content_type = next(
                (value for name, value in response_headers if name.lower() == "content-type"),
                "",
            )
            if response_body and "json" in content_type.lower():
                source_paths = self._server_storage_paths(response_body)
                response_body = rewrite_json_payload(
                    response_body,
                    to_windows=True,
                    server_tmp_dir=self.server_tmp_dir,
                    mirror_dir=self.mirror_dir,
                    mirror_uri=self.mirror_uri,
                )
                if source_paths:
                    self._copy_missing_server_files(source_paths)

            self.send_response(response.status, response.reason)
            connection_header = next(
                (value for name, value in response_headers if name.lower() == "connection"),
                "",
            )
            hop_by_hop = {
                "connection",
                "content-length",
                "keep-alive",
                "proxy-authenticate",
                "proxy-authorization",
                "te",
                "trailer",
                "transfer-encoding",
                "upgrade",
            }
            hop_by_hop.update(token.strip().lower() for token in connection_header.split(","))
            for name, value in response_headers:
                if name.lower() not in hop_by_hop:
                    self.send_header(name, value)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            if self.command != "HEAD" and response_body:
                self.wfile.write(response_body)
        except (OSError, http.client.HTTPException) as error:
            self.send_error(502, f"Unity Catalog upstream unavailable: {error}")
        finally:
            connection.close()

    do_GET = _forward
    do_POST = _forward
    do_PUT = _forward
    do_PATCH = _forward
    do_DELETE = _forward
    do_HEAD = _forward

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=8080)
    parser.add_argument("--target-host", default="127.0.0.1")
    parser.add_argument("--target-port", type=int, default=8081)
    parser.add_argument("--server-tmp-dir", default=os.environ.get("QA_WINDOWS_UC_SERVER_TMP_DIR", ""))
    parser.add_argument("--mirror-dir", default=os.environ.get("QA_WINDOWS_UC_SERVER_MIRROR_DIR", ""))
    parser.add_argument("--mirror-uri", default=os.environ.get("QA_WINDOWS_UC_SERVER_MIRROR_URI", ""))
    args = parser.parse_args()
    # Validate host syntax early and avoid accepting accidental URL paths.
    if urlsplit(f"//{args.target_host}").path:
        parser.error("--target-host must be a host name or IP address")
    UnityCatalogProxy.target_host = args.target_host
    UnityCatalogProxy.target_port = args.target_port
    UnityCatalogProxy.server_tmp_dir = args.server_tmp_dir
    UnityCatalogProxy.mirror_dir = args.mirror_dir
    UnityCatalogProxy.mirror_uri = args.mirror_uri
    server = ThreadingHTTPServer((args.listen_host, args.listen_port), UnityCatalogProxy)
    print(
        f"Unity Catalog Windows URI proxy listening on {args.listen_host}:{args.listen_port}; "
        f"upstream {args.target_host}:{args.target_port}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
