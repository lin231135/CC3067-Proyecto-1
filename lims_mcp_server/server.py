#!/usr/bin/env python3
"""Entry point for the LIMS Food Analysis MCP server.

Runs a hand-built JSON-RPC 2.0 message loop over stdio, exactly as
described by the MCP stdio transport. No MCP SDK (FastMCP or otherwise) is
used anywhere in this project: message framing, parsing, dispatch and
error handling are all implemented from scratch in this package.

Usage:
    python -m lims_mcp_server.server
"""
import json
import sys
import traceback

from . import jsonrpc
from . import protocol
from .database import get_connection


def log(message):
    print(f"[lims-mcp-server] {message}", file=sys.stderr, flush=True)


def main():
    get_connection()  # fail fast if the DB/schema can't be initialized
    log("LIMS MCP server started, waiting for JSON-RPC messages on stdin...")

    while True:
        try:
            raw = sys.stdin.readline()
        except KeyboardInterrupt:
            break

        if raw == "":
            log("stdin closed, shutting down.")
            break

        line = raw.strip()
        if not line:
            continue  # blank lines between messages are allowed

        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            jsonrpc.write_message(jsonrpc.make_error(None, jsonrpc.PARSE_ERROR, f"Invalid JSON: {exc}"))
            continue

        _handle_message(message)


def _handle_message(message):
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        msg_id = message.get("id") if isinstance(message, dict) else None
        jsonrpc.write_message(jsonrpc.make_error(msg_id, jsonrpc.INVALID_REQUEST, "Not a valid JSON-RPC 2.0 message"))
        return

    method = message.get("method")
    msg_id = message.get("id")
    is_notification = "id" not in message

    if not method:
        if not is_notification:
            jsonrpc.write_message(jsonrpc.make_error(msg_id, jsonrpc.INVALID_REQUEST, "Missing 'method'"))
        return

    handler = protocol.METHOD_HANDLERS.get(method)
    if handler is None:
        if not is_notification:
            jsonrpc.write_message(jsonrpc.make_error(msg_id, jsonrpc.METHOD_NOT_FOUND, f"Unknown method: {method}"))
        else:
            log(f"Ignoring unknown notification: {method}")
        return

    params = message.get("params") or {}
    try:
        result = handler(params)
    except Exception:
        log(f"Internal error handling '{method}':\n{traceback.format_exc()}")
        if not is_notification:
            jsonrpc.write_message(jsonrpc.make_error(msg_id, jsonrpc.INTERNAL_ERROR, "Internal server error"))
        return

    if not is_notification:
        jsonrpc.write_message(jsonrpc.make_result(msg_id, result))


if __name__ == "__main__":
    main()
