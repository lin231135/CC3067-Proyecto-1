"""Manual JSON-RPC exercise script for the LIMS MCP server.

Spawns the server as a subprocess and talks to it exactly like a real MCP
host would over stdio: hand-written JSON-RPC requests in, responses out.
Useful to verify the server works end-to-end before wiring it into a
chatbot host (a later phase of this project). Every request/response line
is printed so the raw protocol exchange is visible.

Run with (from the repository root, after seeding the database):
    python tests/manual_client.py
"""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def send(proc, message):
    line = json.dumps(message)
    print(f">> {line}")
    proc.stdin.write(line + "\n")
    proc.stdin.flush()


def recv(proc):
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("Server closed stdout unexpectedly (check stderr below).")
    print(f"<< {line.strip()}")
    return json.loads(line)


def call_tool(proc, next_id, name, arguments):
    send(proc, {"jsonrpc": "2.0", "id": next_id, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    return recv(proc)


def main():
    proc = subprocess.Popen(
        [sys.executable, "-m", "lims_mcp_server.server"],
        cwd=str(REPO_ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    try:
        # 1. Initialization handshake
        send(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "manual-test-client", "version": "0.1"},
            },
        })
        recv(proc)
        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        # 2. Discover the available tools
        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        recv(proc)

        # 3. List whatever is currently pending
        call_tool(proc, 3, "list_pending_samples", {})

        # 4. Register a brand-new sample
        response = call_tool(proc, 4, "register_sample", {
            "client_name": "Panificadora Dona Marta",
            "food_type": "pan de molde",
            "requested_analyses": ["ph", "yeast_mold"],
        })
        sample_code = json.loads(response["result"]["content"][0]["text"])["sample_code"]

        # 5. Check its status right after creation
        call_tool(proc, 5, "get_sample_status", {"sample_code": sample_code})

        # 6. Its results should still be empty (nothing analyzed yet)
        call_tool(proc, 6, "get_analysis_results", {"sample_code": sample_code})

        # 7. A report can still be generated, marked PENDING
        call_tool(proc, 7, "generate_report_summary", {"sample_code": sample_code})

        # 8. Error handling: a sample code that does not exist
        call_tool(proc, 8, "get_sample_status", {"sample_code": "LIMS-1999-9999"})

    finally:
        proc.stdin.close()
        proc.terminate()
        stderr_output = proc.stderr.read()
        if stderr_output:
            print("\n--- server stderr ---")
            print(stderr_output)


if __name__ == "__main__":
    main()
