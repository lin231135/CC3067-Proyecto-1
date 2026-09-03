#!/usr/bin/env python3
"""Remote (HTTP + SSE) transport for the LIMS MCP server.

Implements the MCP "Streamable HTTP" transport by hand on top of Python's
standard library `http.server` -- no web framework (Flask/FastAPI) and no
MCP SDK. It reuses the exact same protocol handlers (protocol.py) and
business logic (tools.py, database.py) as the stdio server in server.py;
only the transport differs, which is what lets the chatbot use the local
and the remote server identically.

Endpoint: POST /mcp
    - A JSON-RPC *request* (has "id"): responds 200 with
      Content-Type: text/event-stream, body is a single `event: message`
      SSE frame carrying the JSON-RPC response, then the stream ends.
    - A JSON-RPC *notification* (no "id"): responds 202 Accepted, empty
      body, per the Streamable HTTP spec.
    - The `initialize` response carries an `Mcp-Session-Id` response
      header. Every later request/notification on the same session must
      echo that header back, or the server answers 400 (missing) / 404
      (unknown or expired session).

GET /mcp is intentionally not implemented as a standalone server-push
stream: every LIMS tool is a quick synchronous request/response and the
server never needs to push unsolicited messages, so that half of the
spec (optional even there) is left out on purpose. GET /health is a
plain liveness probe for Cloud Run.

Usage:
    python -m lims_mcp_server.http_server
    (reads HOST/PORT from the environment, defaulting to 0.0.0.0:8080,
    which matches what Google Cloud Run expects.)
"""
import json
import os
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import jsonrpc, protocol
from .database import get_connection

_sessions = set()
_sessions_lock = threading.Lock()
# sqlite3 connections aren't safe for unrestricted concurrent use across
# threads; ThreadingHTTPServer spawns one thread per request, so every
# call into the shared protocol handlers is serialized here.
_dispatch_lock = threading.Lock()


class MCPHTTPHandler(BaseHTTPRequestHandler):
    server_version = "lims-mcp-http/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[lims-mcp-http] {self.address_string()} - {fmt % args}\n")

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_sse(self, status, payload, session_id=None):
        body = f"event: message\ndata: {json.dumps(payload)}\n\n".encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        if session_id:
            self.send_header("Mcp-Session-Id", session_id)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status, session_id=None):
        self.send_response(status)
        if session_id:
            self.send_header("Mcp-Session-Id", session_id)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/health":
            self._send_json(200, {"status": "ok", "server": "lims-food-analysis-mcp"})
            return
        self.send_response(405)
        self.send_header("Allow", "POST")
        self.end_headers()

    def do_DELETE(self):
        session_id = self.headers.get("Mcp-Session-Id")
        with _sessions_lock:
            _sessions.discard(session_id)
        self._send_empty(204)

    def do_POST(self):
        if self.path.split("?")[0] != "/mcp":
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._send_json(400, jsonrpc.make_error(None, jsonrpc.PARSE_ERROR, f"Invalid JSON: {exc}"))
            return

        method = message.get("method")
        msg_id = message.get("id")
        is_notification = "id" not in message
        is_initialize = method == "initialize"

        session_id = self.headers.get("Mcp-Session-Id")
        if not is_initialize:
            if not session_id:
                self._send_json(
                    400, jsonrpc.make_error(msg_id, jsonrpc.INVALID_REQUEST, "Missing Mcp-Session-Id header")
                )
                return
            with _sessions_lock:
                known = session_id in _sessions
            if not known:
                self._send_json(
                    404, jsonrpc.make_error(msg_id, jsonrpc.INVALID_REQUEST, "Unknown or expired session")
                )
                return

        handler = protocol.METHOD_HANDLERS.get(method)
        if handler is None:
            if is_notification:
                self._send_empty(202)
            else:
                self._send_json(404, jsonrpc.make_error(msg_id, jsonrpc.METHOD_NOT_FOUND, f"Unknown method: {method}"))
            return

        params = message.get("params") or {}
        try:
            with _dispatch_lock:
                result = handler(params)
        except Exception as exc:  # noqa: BLE001 - never crash the server on a bad request
            self.log_message("internal error handling %r: %r", method, exc)
            if not is_notification:
                self._send_json(500, jsonrpc.make_error(msg_id, jsonrpc.INTERNAL_ERROR, "Internal server error"))
            return

        if is_notification:
            self._send_empty(202)
            return

        new_session_id = None
        if is_initialize:
            new_session_id = uuid.uuid4().hex
            with _sessions_lock:
                _sessions.add(new_session_id)

        self._send_sse(200, jsonrpc.make_result(msg_id, result), session_id=new_session_id or session_id)


def main():
    get_connection()  # fail fast if the DB/schema can't be initialized
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    httpd = ThreadingHTTPServer((host, port), MCPHTTPHandler)
    print(f"[lims-mcp-http] Listening on http://{host}:{port}/mcp", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
