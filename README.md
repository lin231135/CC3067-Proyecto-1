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
- [ ] Anthropic API chatbot host, session context, Filesystem + Git MCP demo scenario
- [ ] Remote LIMS MCP server over HTTP + SSE, deployed to Google Cloud Run
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
|   `-- seed.py           # synthetic demo data generator
|-- tests/
|   `-- manual_client.py  # end-to-end JSON-RPC demo/test script
|-- docs/
|   `-- lims_mcp_server_spec.md  # full tool/protocol specification
|-- data/                 # data/lims.db is created here (git-ignored)
`-- README.md
```

## Design notes

- **No MCP SDK.** Per the assignment's explicit requirement, the protocol
  is implemented manually: `jsonrpc.py` handles raw message framing and
  JSON-RPC 2.0 error codes, `protocol.py` implements the MCP-specific
  method semantics (`initialize` handshake, `tools/list`, `tools/call`),
  and `server.py` ties them to stdio.
- **Tool errors vs. protocol errors.** A bad or missing sample code is
  reported inside a normal `tools/call` result (`isError: true`), not as
  a JSON-RPC error -- this matches the MCP spec's guidance so an LLM host
  can see the failure and react to it in conversation.
- **stdio framing.** Each JSON-RPC message is exactly one line; the
  server never writes anything except protocol messages to stdout, so
  logging goes to stderr instead.

## Academic integrity

Developed individually for CC3067 - Redes, UVG. No third-party MCP
libraries or SDKs were used, per the assignment's requirements.

