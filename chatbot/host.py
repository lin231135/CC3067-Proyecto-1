"""Console chatbot host.

Connects to the Anthropic Messages API and orchestrates tool calls across
three MCP servers: the official Filesystem and Git servers, and this
repository's own local LIMS server. Maintains conversation context across
turns and logs every MCP request/response.

Run with (from the repository root):
    python -m chatbot.host
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from .anthropic_client import AnthropicClient, AnthropicError
from .logging_utils import InteractionLogger
from .mcp.stdio_client import MCPError, MCPStdioClient

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVERS_CONFIG_PATH = Path(__file__).resolve().parent / "servers_config.json"
WORKSPACE_PATH = REPO_ROOT / "workspace"
DEMO_REPO_PATH = WORKSPACE_PATH / "demo-repo"

SYSTEM_PROMPT = (
    "You are the assistant for a food-safety testing laboratory. Answer general "
    "questions from your own knowledge. You also have tools to: (1) read/write files "
    "under a sandboxed workspace directory via the Filesystem MCP server, (2) inspect "
    "and commit to git repositories via the Git MCP server, and (3) manage lab samples "
    "via the LIMS MCP server (register_sample, get_sample_status, get_analysis_results, "
    "list_pending_samples, generate_report_summary). Use a tool whenever the request "
    "needs real, current, or system-specific data instead of guessing.\n\n"
    f"Always pass ABSOLUTE paths to filesystem and git tools. The sandboxed workspace "
    f"root is '{WORKSPACE_PATH}'. A pre-initialized, empty git repository is available "
    f"at '{DEMO_REPO_PATH}' for demo purposes (e.g. writing a README with the Filesystem "
    f"server, then staging and committing it with the Git server)."
)

SUGGESTED_DEMO_PROMPT = (
    "In the demo-repo git repository, create a README.md that briefly describes the "
    "LIMS food-safety project, stage it, and commit it with an appropriate message."
)


def load_env_file(path):
    """Tiny .env loader (KEY=VALUE per line) so a local, git-ignored .env file can hold
    ANTHROPIC_API_KEY without needing python-dotenv as a dependency."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def bootstrap_demo_repo():
    """Ensure workspace/demo-repo exists as an (empty) git repository.

    The publicly published build of the official Git MCP server (`uvx
    mcp-server-git`, v1.30.0) does not expose a `git_init` tool -- verified
    by inspecting its `tools/list` response and its installed source, which
    has no init handler at all. So repository *creation* for the
    assignment's demo scenario is bootstrapped here with a direct `git
    init` subprocess call; everything after this point (writing the
    README, `git add`, `git commit`) is still driven by the chatbot
    through the official Filesystem and Git MCP servers, not by this
    bootstrap step.
    """
    if (DEMO_REPO_PATH / ".git").exists():
        return
    DEMO_REPO_PATH.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(DEMO_REPO_PATH), check=True, capture_output=True)


def load_servers_config():
    with open(SERVERS_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["servers"]


def connect_servers(logger):
    clients = {}
    for entry in load_servers_config():
        name = entry["name"]
        try:
            client = MCPStdioClient(
                name=name,
                command=entry["command"],
                args=entry.get("args", []),
                cwd=str(REPO_ROOT),
                logger=logger,
            )
            client.initialize()
            clients[name] = client
            print(f"[host] Connected to '{name}' ({len(client.tools)} tools).", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - one bad server shouldn't kill the whole host
            print(f"[host] Could not start MCP server '{name}': {exc}", file=sys.stderr)
    return clients


def build_tool_catalog(clients):
    """Returns (anthropic_tools, tool_to_server) merged from every connected client."""
    anthropic_tools = []
    tool_to_server = {}
    for server_name, client in clients.items():
        for tool in client.tools:
            if tool["name"] in tool_to_server:
                raise RuntimeError(f"Duplicate tool name '{tool['name']}' from multiple MCP servers")
            anthropic_tools.append({
                "name": tool["name"],
                "description": tool.get("description", ""),
                "input_schema": tool["inputSchema"],
            })
            tool_to_server[tool["name"]] = server_name
    return anthropic_tools, tool_to_server


def run_tool(clients, tool_to_server, tool_name, arguments):
    server_name = tool_to_server.get(tool_name)
    if server_name is None:
        return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}]}
    try:
        return clients[server_name].call_tool(tool_name, arguments)
    except MCPError as exc:
        return {"isError": True, "content": [{"type": "text", "text": str(exc)}]}


def agent_turn(anthropic_client, messages, tools, clients, tool_to_server):
    """Runs the tool-use loop for one user turn, mutating `messages` in place.

    Keeps calling the API and executing any requested tools until the
    model returns a plain text answer (no more tool_use blocks), which is
    what preserves conversation context across the whole session.
    """
    while True:
        response = anthropic_client.create_message(messages=messages, system=SYSTEM_PROMPT, tools=tools)
        content = response["content"]
        messages.append({"role": "assistant", "content": content})

        tool_uses = [block for block in content if block["type"] == "tool_use"]
        if not tool_uses:
            return "".join(block["text"] for block in content if block["type"] == "text")

        tool_results = []
        for block in tool_uses:
            print(f"  -> {block['name']}({json.dumps(block['input'], ensure_ascii=False)})", file=sys.stderr)
            result = run_tool(clients, tool_to_server, block["name"], block["input"])
            text = "\n".join(part.get("text", "") for part in result.get("content", []))
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block["id"],
                "content": text,
                "is_error": result.get("isError", False),
            })
        messages.append({"role": "user", "content": tool_results})


def main():
    load_env_file(REPO_ROOT / ".env")
    bootstrap_demo_repo()

    try:
        anthropic_client = AnthropicClient()
    except AnthropicError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    logger = InteractionLogger(echo=False)
    clients = connect_servers(logger)
    if not clients:
        print("No MCP servers could be started; exiting.", file=sys.stderr)
        sys.exit(1)

    tools, tool_to_server = build_tool_catalog(clients)
    print(f"[host] {len(tools)} tools available across {len(clients)} server(s): {list(clients)}\n", file=sys.stderr)

    messages = []
    print("LIMS lab assistant ready. Commands: /log, /tools, /exit")
    print(f"Try: \"{SUGGESTED_DEMO_PROMPT}\"\n")
    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                break
            if not user_input:
                continue
            if user_input == "/exit":
                break
            if user_input == "/log":
                for entry in logger.dump():
                    print(json.dumps(entry, ensure_ascii=False))
                continue
            if user_input == "/tools":
                for t in tools:
                    print(f"- {t['name']} ({tool_to_server[t['name']]}): {t['description']}")
                continue

            messages.append({"role": "user", "content": user_input})
            try:
                reply = agent_turn(anthropic_client, messages, tools, clients, tool_to_server)
            except AnthropicError as exc:
                print(f"[error] {exc}")
                messages.pop()  # drop the failed turn so a retry starts clean
                continue
            print(f"\nAssistant: {reply}\n")
    finally:
        for client in clients.values():
            client.close()


if __name__ == "__main__":
    main()
