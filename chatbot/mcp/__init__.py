"""Hand-built MCP client implementations (no MCP SDK).

- jsonrpc_client.py: transport-agnostic JSON-RPC 2.0 message helpers.
- stdio_client.py: MCP client over a subprocess's stdin/stdout.
- http_client.py (added in a later commit): MCP client over HTTP + SSE.
"""
