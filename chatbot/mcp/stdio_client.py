"""Generic stdio MCP client.

Spawns any MCP server as a subprocess and speaks JSON-RPC 2.0 to it by
hand over its stdin/stdout, exactly as lims_mcp_server/server.py expects
on the other end. Because it only depends on the wire protocol, this same
class talks to the official Filesystem and Git MCP servers just as well
as it talks to our own lims_mcp_server -- no per-server special casing.
"""
import subprocess

from .jsonrpc_client import make_notification, make_request, read_message, write_message

CLIENT_INFO = {"name": "cc3067-chatbot-host", "version": "1.0.0"}
PROTOCOL_VERSION = "2025-06-18"


class MCPError(Exception):
    """Raised when an MCP server returns a JSON-RPC error or closes unexpectedly."""


class MCPStdioClient:
    def __init__(self, name, command, args=None, cwd=None, env=None, logger=None):
        self.name = name
        self.logger = logger
        self.tools = []
        self.proc = subprocess.Popen(
            [command, *(args or [])],
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def _send(self, message):
        direction = "request" if "id" in message else "notification"
        if self.logger:
            self.logger.log(self.name, direction, message)
        write_message(message, self.proc.stdin)

    def _recv(self):
        message = read_message(self.proc.stdout)
        if message is None:
            stderr = self.proc.stderr.read()
            raise MCPError(f"[{self.name}] server closed the connection unexpectedly. stderr:\n{stderr}")
        if self.logger:
            self.logger.log(self.name, "response", message)
        return message

    def initialize(self):
        self._send(make_request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        }))
        response = self._recv()
        if "error" in response:
            raise MCPError(f"[{self.name}] initialize failed: {response['error']}")
        self._send(make_notification("notifications/initialized"))
        self.tools = self._list_tools()
        return response["result"]

    def _list_tools(self):
        self._send(make_request("tools/list"))
        response = self._recv()
        if "error" in response:
            raise MCPError(f"[{self.name}] tools/list failed: {response['error']}")
        return response["result"]["tools"]

    def call_tool(self, tool_name, arguments):
        self._send(make_request("tools/call", {"name": tool_name, "arguments": arguments}))
        response = self._recv()
        if "error" in response:
            raise MCPError(f"[{self.name}] tools/call failed: {response['error']}")
        return response["result"]

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        self.proc.terminate()
