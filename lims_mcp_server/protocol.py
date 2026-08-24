"""MCP method handlers built directly on top of the JSON-RPC 2.0 layer.

Implements the subset of the MCP lifecycle and tools primitives this server
needs: initialize, notifications/initialized, ping, tools/list, tools/call.
No resources or prompts capability is advertised or implemented.
"""
import json
import sys

from . import tools as tools_module

# The server accepts any of these protocol versions; if the client asks for
# one we don't recognize we fall back to negotiating our latest supported
# version, per the MCP initialization handshake.
SUPPORTED_PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

SERVER_INFO = {
    "name": "lims-food-analysis-mcp",
    "version": "1.0.0",
}

SERVER_INSTRUCTIONS = (
    "This server manages samples for a food-safety testing laboratory (LIMS). "
    "Use register_sample to log a new sample, get_sample_status / "
    "get_analysis_results to check on one, list_pending_samples to see "
    "everything still awaiting results, and generate_report_summary to "
    "produce a client-ready report."
)


def handle_initialize(params):
    requested_version = params.get("protocolVersion")
    negotiated = (
        requested_version if requested_version in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
    )
    return {
        "protocolVersion": negotiated,
        "capabilities": {
            "tools": {"listChanged": False},
        },
        "serverInfo": SERVER_INFO,
        "instructions": SERVER_INSTRUCTIONS,
    }


def handle_initialized(params):
    return {}


def handle_ping(params):
    return {}


def handle_tools_list(params):
    return {"tools": tools_module.TOOL_DEFINITIONS}


def handle_tools_call(params):
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not name:
        return {
            "content": [{"type": "text", "text": "Missing required 'name' field in tools/call params."}],
            "isError": True,
        }

    try:
        result = tools_module.dispatch(name, arguments)
    except tools_module.ToolError as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    except Exception as exc:  # noqa: BLE001 - deliberately broad: never crash the server on a bad tool call
        print(f"[lims-mcp-server] Unexpected error in tool '{name}': {exc!r}", file=sys.stderr, flush=True)
        return {
            "content": [{"type": "text", "text": f"Internal error while executing tool '{name}'."}],
            "isError": True,
        }

    if name == "generate_report_summary":
        text = result["report_text"]
    else:
        text = json.dumps(result, indent=2, ensure_ascii=False)

    return {"content": [{"type": "text", "text": text}], "isError": False}


METHOD_HANDLERS = {
    "initialize": handle_initialize,
    "notifications/initialized": handle_initialized,
    "ping": handle_ping,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
}
