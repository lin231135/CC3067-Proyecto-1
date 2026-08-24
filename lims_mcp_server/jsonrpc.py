"""Minimal JSON-RPC 2.0 message helpers for the MCP stdio transport.

Every request, response, notification and error object used by this project
is built and parsed by hand here -- no MCP SDK (e.g. FastMCP) is used
anywhere, per the assignment's explicit requirement.

Per the MCP stdio transport, messages are newline-delimited JSON objects
that must not contain embedded newlines.
"""
import json
import sys

JSONRPC_VERSION = "2.0"

# Standard JSON-RPC 2.0 error codes (https://www.jsonrpc.org/specification)
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def write_message(message, stream=None):
    """Serialize message as a single line of JSON and flush immediately."""
    stream = stream or sys.stdout
    stream.write(json.dumps(message, ensure_ascii=False))
    stream.write("\n")
    stream.flush()


def make_result(request_id, result):
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def make_error(request_id, code, message, data=None):
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error}
