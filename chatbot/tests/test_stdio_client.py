"""Smoke test for MCPStdioClient.

Connects to our own lims_mcp_server over stdio using the generic client
built in this commit, proving the hand-built client and server sides of
the protocol talk to each other correctly before the Anthropic API and
the other MCP servers (Filesystem, Git) are wired in.

Run with (from the repository root, after seeding the database -- see
the main README):
    python chatbot/tests/test_stdio_client.py
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from chatbot.logging_utils import InteractionLogger  # noqa: E402
from chatbot.mcp.stdio_client import MCPStdioClient  # noqa: E402


def main():
    logger = InteractionLogger(echo=True)
    client = MCPStdioClient(
        name="lims",
        command=sys.executable,
        args=["-m", "lims_mcp_server.server"],
        cwd=str(REPO_ROOT),
        logger=logger,
    )
    try:
        info = client.initialize()
        print(f"\nConnected to: {info['serverInfo']['name']} v{info['serverInfo']['version']}")
        print(f"Discovered {len(client.tools)} tools: {[t['name'] for t in client.tools]}")

        result = client.call_tool("list_pending_samples", {})
        text = result["content"][0]["text"]
        print("\ntools/call result (list_pending_samples), first 300 chars:")
        print(text[:300], "...")

        print(f"\nLogged {len(logger.dump())} interactions to {logger.log_file}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
