# CC3067 - Project 1: Use of an Existing Protocol (MCP)

Universidad del Valle de Guatemala -- CC3067 Redes -- Section 20

This repository implements the **Model Context Protocol (MCP)** for
Project 1. It will eventually contain a full chatbot host that combines
official MCP servers (Filesystem, Git) with a custom local/remote MCP
server. **This delivery is the partial submission requested by the
assignment: the local MCP server only**, built from scratch on top of
JSON-RPC 2.0, with no MCP SDK (no FastMCP or similar) involved anywhere.

## Use case: LIMS for a food-safety testing laboratory

The server models a Laboratory Information Management System (LIMS) for a
lab that receives food samples (from processing plants, restaurants,
exporters, etc.) and runs physicochemical/microbiological analyses (pH,
fecal coliforms, Salmonella, total aerobic count, moisture, water
activity, Staphylococcus aureus, E. coli, Listeria, yeast & mold) on them.
A chatbot connected to this server would let lab staff ask things like:

- *"What samples from Alimentos del Sur are still pending results?"*
- *"Register a new milk sample from Lacteos San Miguel for pH and
  Salmonella testing."*
- *"Give me the report for sample LIMS-2026-0032."*

Full specification, tool schemas, and usage examples:
[`docs/lims_mcp_server_spec.md`](docs/lims_mcp_server_spec.md).

## Features implemented in this delivery

- A hand-built JSON-RPC 2.0 message loop over **stdio**
  (`lims_mcp_server/server.py`, `jsonrpc.py`): no MCP SDK is used, all
  message framing/parsing/dispatch is manual.
- The MCP lifecycle: `initialize`, `notifications/initialized`, `ping`.
- Tool discovery (`tools/list`) and invocation (`tools/call`) with JSON
  Schema `inputSchema` for every tool.
- Five domain tools (`lims_mcp_server/tools.py`):
  `register_sample`, `get_sample_status`, `get_analysis_results`,
  `list_pending_samples`, `generate_report_summary`.
- A SQLite database (`sqlite3` from the standard library only, no ORM)
  with `clients`, `samples`, `analysis_parameters`, `results` tables.
- A synthetic data generator (`lims_mcp_server/seed.py`) that populates
  50-100 realistic samples across 10 clients.
- A manual JSON-RPC test client (`tests/manual_client.py`) that spawns
  the server and exercises every tool end-to-end, printing the raw
  protocol exchange.

Not yet part of this delivery (later phases of the project, per the
assignment): the chatbot host itself, the Filesystem/Git official MCP
servers, the remote (Cloud Run) deployment of this same server, and the
Wireshark traffic analysis.

## Project status

- [x] Local LIMS MCP server (`lims_mcp_server/`), manual JSON-RPC over stdio
- [x] Generic MCP client + interaction logger (`chatbot/`), verified against the LIMS server (`chatbot/tests/test_stdio_client.py`)
- [x] Anthropic API chatbot host, session context, Filesystem + Git MCP demo scenario
- [x] Remote transport for the LIMS server (HTTP + SSE, manual, same tools/business logic as the stdio server) + Dockerfile
- [ ] Actual deployment to Google Cloud Run (needs your GCP account -- see below)
- [ ] Wireshark capture and JSON-RPC message classification
- [ ] Final report (spec, OSI/TCP-IP layer analysis, conclusions)

## Requirements

- Python 3.10 or later
- No external dependencies -- everything used (`json`, `sqlite3`, `sys`,
  `argparse`, `datetime`, `random`, `subprocess`) is part of the Python
  standard library.

## Installation

```bash
git clone https://github.com/lin231135/CC3067-Proyecto-1.git
cd CC3067-Proyecto-1
```

No virtual environment or `pip install` is strictly necessary since there
are no third-party dependencies, but you may create one if you prefer:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
```

## Usage

### 1. Seed the database with demo data

Run this once (or any time you want to reset the demo data):

```bash
python -m lims_mcp_server.seed --samples 80
```

This creates `data/lims.db` with 10 clients, the 10-parameter test
catalog, and 80 samples in a realistic mix of `received` /
`in_analysis` / `finalized` states.

Options: `--samples N` (default 80, valid range for the use case is
50-100) and `--seed N` (random seed, default 42, for reproducibility).

### 2. Run the automated demo client

The easiest way to see the server working end-to-end (handshake, tool
discovery, and all 5 tools, including the error path for an unknown
sample) is:

```bash
python tests/manual_client.py
```

It prints every JSON-RPC message sent (`>>`) and received (`<<`).

### 3. Run the server by itself

```bash
python -m lims_mcp_server.server
```

The server waits for JSON-RPC 2.0 requests on stdin and writes responses
to stdout (diagnostic logs go to stderr). You can drive it manually by
typing JSON-RPC messages, one per line, for example:

```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "manual", "version": "0.1"}}}
{"jsonrpc": "2.0", "method": "notifications/initialized"}
{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_pending_samples", "arguments": {}}}
```

Press `Ctrl+D` (macOS/Linux) or `Ctrl+Z` then Enter (Windows) to close
stdin and stop the server.

### 4. (Optional) Verify with Claude Desktop

As recommended by the assignment, you can also point Claude Desktop at
this server to confirm it behaves like a real MCP tool provider. Add this
to your `claude_desktop_config.json` (adjust the path to your clone):

```json
{
  "mcpServers": {
    "lims-food-analysis": {
      "command": "python",
      "args": ["-m", "lims_mcp_server.server"],
      "cwd": "C:/github/CC3067-Proyecto-1"
    }
  }
}
```

Restart Claude Desktop and ask it something like *"What food samples are
pending results?"* -- it should call `list_pending_samples` automatically.

## Chatbot host

`chatbot/` is the MCP **host**: a console chatbot that talks to the
Anthropic Messages API directly over HTTPS (`urllib`, no `anthropic` pip
package) and orchestrates three MCP servers at once, all connected
through the same hand-built stdio client (`chatbot/mcp/`):

| Server | Role | Command |
|---|---|---|
| `filesystem` | Official Anthropic Filesystem MCP server, sandboxed to `./workspace` | `npx -y @modelcontextprotocol/server-filesystem ./workspace` |
| `git` | Official Anthropic Git MCP server | `uvx mcp-server-git` |
| `lims` | This repository's own local server | `python -m lims_mcp_server.server` |

Features: connects with the LLM at the raw API level, keeps full
conversation context across turns (multi-server tool-use loop), and logs
every MCP request/response (`InteractionLogger`, viewable in-session with
`/log`).

### Prerequisites

- **Node.js** (for `npx`, which runs the Filesystem server) --
  https://nodejs.org
- **uv** (for `uvx`, which runs the Git server) --
  https://docs.astral.sh/uv/getting-started/installation/
- An **Anthropic API key** -- create one at
  https://console.anthropic.com/ (the assignment notes $5 of free credit
  is enough for this project)

### Setup

Copy `.env.example` to `.env` and fill in your key (or export the same
variables directly in your shell -- both work, `.env` is git-ignored):

```bash
cp .env.example .env
# then edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

### Run it

```bash
python -m chatbot.host
```

On startup the host connects to all three servers (skipping any that
fail to start, with a warning) and prints how many tools it found. Try
the assignment's required demo scenario:

```
You: In the demo-repo git repository, create a README.md that briefly
     describes the LIMS food-safety project, stage it, and commit it
     with an appropriate message.
```

The model will call `write_file` (Filesystem server) to create the file,
then `git_add` and `git_commit` (Git server) to stage and commit it --
you'll see each tool call printed to the console as it happens. You can
also ask LIMS questions in the same session (e.g. *"What samples are
pending results?"*) and general-knowledge questions (e.g. *"Who was Alan
Turing?"* followed by *"When was he born?"*, to see session context
carried across turns).

In-session commands: `/tools` (list every discovered tool and which
server owns it), `/log` (dump the full MCP interaction log for this
session), `/exit`.

### A note on the demo scenario

The publicly published build of the official Git MCP server (`uvx
mcp-server-git`, v1.30.0) does not expose a `git_init` tool -- verified
directly against its `tools/list` response and its installed source
(`git_status`, `git_diff*`, `git_commit`, `git_add`, `git_reset`,
`git_log`, `git_create_branch`, `git_checkout`, `git_show`, `git_branch`
is the complete list; no init handler exists). Since the chatbot cannot
create a git repository through a tool the server doesn't offer,
`chatbot/host.py` bootstraps an empty git repository at
`workspace/demo-repo` on startup with a direct `git init` call. Every
step after that -- writing the README, staging it, committing it -- is
still performed by the LLM through the official Filesystem and Git MCP
servers, exactly as the assignment asks.

## Remote transport (HTTP + SSE)

`lims_mcp_server/http_server.py` is the **same server** (`protocol.py`,
`tools.py`, `database.py` are untouched and shared) exposed over a
different, manually-implemented transport: MCP's "Streamable HTTP"
transport, hand-built on Python's stdlib `http.server` (no Flask/FastAPI,
no MCP SDK).

- `POST /mcp` -- send one JSON-RPC message per request. A request (has
  `id`) gets back `200` with `Content-Type: text/event-stream` (a single
  SSE `event: message` frame carrying the JSON-RPC response); a
  notification (no `id`) gets back `202 Accepted` with an empty body.
- `initialize` responds with an `Mcp-Session-Id` header; every later call
  must echo that header back, or the server answers `400` (missing) /
  `404` (unknown session) -- verified with `curl` during development.
- `GET /health` is a plain liveness probe for Cloud Run. `GET /mcp`
  intentionally returns `405`: every LIMS tool is a quick synchronous
  call, so the server never needs the optional server-initiated push
  stream the spec also allows for.
- `chatbot/mcp/http_client.py` is the client-side counterpart -- same
  shape as the stdio client (`initialize`, `call_tool`, `.tools`,
  `close`), so `chatbot/host.py` uses a local (stdio) or a remote (HTTP)
  MCP server identically, exactly as the assignment requires.

### Run it locally

```bash
python -m lims_mcp_server.http_server
# in another terminal:
curl http://localhost:8080/health
```

### Run it in Docker locally

```bash
docker build -t lims-mcp-server .
docker run --rm -p 8080:8080 lims-mcp-server
curl http://localhost:8080/health
```

### Use it from the chatbot

Edit `chatbot/servers_config.json`: set `"enabled": false` on the local
`lims` entry and `"enabled": true` (with the real `base_url`) on
`lims-remote`, then run `python -m chatbot.host` as usual -- the host
doesn't need any other change, since both clients implement the same
interface.

### Deploying to Google Cloud Run

Deploying requires your own Google Cloud account and `gcloud` CLI login,
so it has to be run by you, not from here. See
[`docs/deployment.md`](docs/deployment.md) for the full step-by-step
guide (build, push, `gcloud run deploy`, and how to plug the resulting
URL into `servers_config.json`).

## Project structure

```
CC3067-Proyecto-1/
|-- lims_mcp_server/
|   |-- server.py        # stdin/stdout JSON-RPC event loop (entry point)
|   |-- jsonrpc.py        # JSON-RPC 2.0 message read/write + error codes
|   |-- protocol.py       # MCP method handlers (initialize, tools/list, tools/call)
|   |-- tools.py          # the 5 domain tools + their JSON Schemas
|   |-- database.py       # SQLite connection management
|   |-- schema.sql         # table definitions
|   |-- seed.py           # synthetic demo data generator
|   `-- http_server.py    # remote transport: HTTP + SSE (entry point for Cloud Run)
|-- chatbot/
|   |-- host.py           # console chatbot host (entry point: python -m chatbot.host)
|   |-- anthropic_client.py  # raw HTTPS Anthropic Messages API client
|   |-- logging_utils.py  # InteractionLogger (MCP request/response log)
|   |-- servers_config.json  # the MCP servers the host connects to (local + remote)
|   `-- mcp/
|       |-- jsonrpc_client.py  # client-side JSON-RPC 2.0 helpers
|       |-- stdio_client.py    # generic MCP client over a subprocess's stdio
|       `-- http_client.py     # generic MCP client over HTTP + SSE
|-- tests/
|   `-- manual_client.py  # end-to-end JSON-RPC demo/test script for lims_mcp_server
|-- chatbot/tests/
|   `-- test_stdio_client.py  # smoke test for the generic MCP client
|-- docs/
|   |-- lims_mcp_server_spec.md  # full tool/protocol specification
|   `-- deployment.md            # Google Cloud Run deployment walkthrough
|-- Dockerfile             # container image for the remote server
|-- data/                 # data/lims.db and logs/ are created here (git-ignored)
|-- workspace/            # sandbox root for the Filesystem/Git MCP demo (git-ignored)
`-- README.md
```

## Design notes

- **No MCP SDK.** Per the assignment's explicit requirement, the protocol
  is implemented manually on both ends: `lims_mcp_server/jsonrpc.py` and
  `chatbot/mcp/jsonrpc_client.py` handle raw message framing and JSON-RPC
  2.0 error codes, `protocol.py` implements the MCP-specific method
  semantics server-side, and `chatbot/mcp/stdio_client.py` implements the
  handshake/discovery/invocation sequence client-side.
- **No Anthropic SDK either.** `chatbot/anthropic_client.py` calls the
  Messages API with plain `urllib` HTTPS requests, in line with objective
  #5 of the assignment (understand how to interact with an LLM at the API
  level) and keeping the project dependency-free.
- **Tool errors vs. protocol errors.** A bad or missing sample code (or
  any other tool-level failure) is reported inside a normal `tools/call`
  result (`isError: true`), not as a JSON-RPC error -- this matches the
  MCP spec's guidance so an LLM host can see the failure and react to it
  in conversation.
- **stdio framing.** Each JSON-RPC message is exactly one line; servers
  never write anything except protocol messages to stdout, so logging
  goes to stderr instead.
- **Windows subprocess quirk.** `npx`/`uvx` are `.cmd`/`.exe` shims;
  `subprocess.Popen` without `shell=True` fails to find them via a plain
  `PATH` lookup on Windows (`WinError 2`). `stdio_client.py` resolves the
  command with `shutil.which()` first, which is PATHEXT-aware on Windows
  and a no-op on POSIX.
- **One business logic, two transports.** `http_server.py` imports and
  calls `protocol.METHOD_HANDLERS` directly -- the exact same dispatch
  table `server.py` uses over stdio -- so the remote server is
  guaranteed to behave identically to the local one; only message
  framing (newline-delimited stdio vs. HTTP + SSE) and session handling
  differ. `ThreadingHTTPServer` serves requests concurrently, so a single
  lock serializes access to the shared SQLite connection across threads.

## Academic integrity

Developed individually for CC3067 - Redes, UVG. No third-party MCP
libraries or SDKs were used, per the assignment's requirements.

