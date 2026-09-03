"""Generic MCP client over the Streamable HTTP + SSE transport.

Talks to any MCP server that implements the transport the way
lims_mcp_server/http_server.py does: POST a single JSON-RPC message to
`<base_url>/mcp`, then read back either one SSE `event: message` frame
(for a request) or a 202 Accepted with an empty body (for a
notification), tracking the `Mcp-Session-Id` the server hands back on
`initialize`. Exposes the same shape as MCPStdioClient (initialize,
call_tool, .tools, close) so chatbot/host.py can treat a local stdio
server and a remote HTTP server identically.
"""
import json
import urllib.error
import urllib.request

from .jsonrpc_client import make_notification, make_request

CLIENT_INFO = {"name": "cc3067-chatbot-host", "version": "1.0.0"}
PROTOCOL_VERSION = "2025-06-18"


class MCPError(Exception):
    pass


class MCPHTTPClient:
    def __init__(self, name, base_url, logger=None, timeout=15):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.logger = logger
        self.timeout = timeout
        self.session_id = None
        self.tools = []

    def _post(self, message):
        direction = "request" if "id" in message else "notification"
        if self.logger:
            self.logger.log(self.name, direction, message)

        headers = {"content-type": "application/json"}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        request = urllib.request.Request(
            f"{self.base_url}/mcp",
            data=json.dumps(message).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            raise MCPError(f"[{self.name}] HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise MCPError(f"[{self.name}] could not reach {self.base_url}: {exc}") from exc

        session_header = response.headers.get("Mcp-Session-Id")
        if session_header:
            self.session_id = session_header

        if direction == "notification":
            return None

        raw = response.read().decode("utf-8")
        result = json.loads(_extract_sse_data(raw))
        if self.logger:
            self.logger.log(self.name, "response", result)
        return result

    def initialize(self):
        response = self._post(make_request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        }))
        if "error" in response:
            raise MCPError(f"[{self.name}] initialize failed: {response['error']}")
        self._post(make_notification("notifications/initialized"))
        self.tools = self._list_tools()
        return response["result"]

    def _list_tools(self):
        response = self._post(make_request("tools/list"))
        if "error" in response:
            raise MCPError(f"[{self.name}] tools/list failed: {response['error']}")
        return response["result"]["tools"]

    def call_tool(self, tool_name, arguments):
        response = self._post(make_request("tools/call", {"name": tool_name, "arguments": arguments}))
        if "error" in response:
            raise MCPError(f"[{self.name}] tools/call failed: {response['error']}")
        return response["result"]

    def close(self):
        pass  # a plain request/response HTTP client holds no persistent connection to release


def _extract_sse_data(raw_text):
    """Pull the JSON payload out of a single `event: message\\ndata: {...}` SSE frame."""
    for line in raw_text.splitlines():
        if line.startswith("data:"):
            return line[len("data:"):].strip()
    raise MCPError(f"No 'data:' line found in SSE response: {raw_text!r}")
