#!/usr/bin/env python3
"""Bridge Unity Catalog file URIs between native Windows and its WSL server."""

from __future__ import annotations

import argparse
import http.client
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit


WSL_TMP_URI = re.compile(r"(?i)file:///tmp/")
WINDOWS_TMP_URI = re.compile(r"(?i)file:///W:/tmp/")


def translate_value(value: Any, *, to_windows: bool) -> Any:
    if isinstance(value, str):
        if to_windows:
            return WSL_TMP_URI.sub("file:///W:/tmp/", value)
        return WINDOWS_TMP_URI.sub("file:///tmp/", value)
    if isinstance(value, list):
        return [translate_value(item, to_windows=to_windows) for item in value]
    if isinstance(value, dict):
        return {key: translate_value(item, to_windows=to_windows) for key, item in value.items()}
    return value


def rewrite_json_payload(payload: bytes, *, to_windows: bool) -> bytes:
    """Translate file URIs recursively in a JSON request or response body."""
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return payload
    return json.dumps(translate_value(value, to_windows=to_windows), separators=(",", ":")).encode()


class UnityCatalogProxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    target_host = "127.0.0.1"
    target_port = 8081

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
            body = rewrite_json_payload(body, to_windows=False)

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
                response_body = rewrite_json_payload(response_body, to_windows=True)

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
    args = parser.parse_args()
    # Validate host syntax early and avoid accepting accidental URL paths.
    if urlsplit(f"//{args.target_host}").path:
        parser.error("--target-host must be a host name or IP address")
    UnityCatalogProxy.target_host = args.target_host
    UnityCatalogProxy.target_port = args.target_port
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
