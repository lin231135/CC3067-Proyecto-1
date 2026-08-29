"""Client-side JSON-RPC 2.0 message helpers.

Mirrors lims_mcp_server/jsonrpc.py but from the caller's side: building
requests/notifications instead of responses, and reading/writing
arbitrary text streams (a subprocess pipe today, an HTTP/SSE stream in a
later commit) instead of always defaulting to sys.stdin/stdout.

No MCP SDK is used here either -- this is the same hand-rolled JSON-RPC
2.0 framing as the server side, just used in the opposite direction.
"""
import itertools
import json

JSONRPC_VERSION = "2.0"

_id_counter = itertools.count(1)


def next_id():
    return next(_id_counter)


def make_request(method, params=None, request_id=None):
    message = {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id if request_id is not None else next_id(),
        "method": method,
    }
    if params is not None:
        message["params"] = params
    return message


def make_notification(method, params=None):
    message = {"jsonrpc": JSONRPC_VERSION, "method": method}
    if params is not None:
        message["params"] = params
    return message


def write_message(message, stream):
    """Serialize message as a single line of JSON and flush immediately."""
    stream.write(json.dumps(message, ensure_ascii=False))
    stream.write("\n")
    stream.flush()


def read_message(stream):
    """Read one newline-delimited JSON-RPC message. Returns None on EOF."""
    while True:
        line = stream.readline()
        if line == "":
            return None
        line = line.strip()
        if not line:
            continue
        return json.loads(line)
