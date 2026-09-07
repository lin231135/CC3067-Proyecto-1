# Final Report

CC3067 - Redes, UVG. Project 1: Use of an Existing Protocol (MCP).

This report covers items 8-10 of the assignment: the specification of
the MCP servers built for this project, the Wireshark-based
protocol/layer analysis, and conclusions. It summarizes and links to the
more detailed documents already in this repository rather than
duplicating them.

## 1. Servers developed (assignment item 8)

Two MCP servers were built for this project, both implementing the LIMS
(food-safety testing lab) use case described in the original proposal,
sharing the exact same business logic (`lims_mcp_server/tools.py`,
`database.py`, `protocol.py`) over two different, hand-built transports:

| | Local server | Remote server |
|---|---|---|
| Transport | stdio, newline-delimited JSON-RPC 2.0 | Streamable HTTP + SSE |
| Entry point | `python -m lims_mcp_server.server` | `python -m lims_mcp_server.http_server` |
| Where it runs | The developer's machine, spawned by the chatbot host | **Live**: `https://cc3067-lims-mcp.onrender.com` |
| Session state | Implicit (one process per connection) | Explicit `Mcp-Session-Id` header, issued on `initialize` |

Full specification -- the 5 tools (`register_sample`,
`get_sample_status`, `get_analysis_results`, `list_pending_samples`,
`generate_report_summary`), their JSON Schemas, example calls/results,
the analysis-parameter catalog, and the SQLite data model -- is in
[`lims_mcp_server_spec.md`](lims_mcp_server_spec.md). The HTTP + SSE
transport's endpoints (`POST /mcp`, `GET /health`, session handling,
error codes) are documented in the main
[README](../README.md#remote-transport-http--sse). Deployment steps
(and why the remote server ended up on Render instead of the originally
proposed Google Cloud Run) are in [`deployment.md`](deployment.md).

No MCP SDK (e.g. FastMCP) and no Anthropic SDK were used anywhere in the
project, per the assignment's requirement: `lims_mcp_server/jsonrpc.py`,
`chatbot/mcp/jsonrpc_client.py`, `chatbot/mcp/stdio_client.py`,
`chatbot/mcp/http_client.py`, and `chatbot/anthropic_client.py` all
implement their respective protocols by hand.

### Project status at the time of this report

- [x] Local LIMS MCP server -- implemented, tested end-to-end.
- [x] Chatbot host (Anthropic API, session context, interaction log,
      Filesystem + Git + LIMS orchestration) -- **fully verified live**
      against the real Anthropic API (`claude-haiku-4-5-20251001`) and
      the real deployed remote LIMS server: the model independently
      chose to call `list_pending_samples` for a LIMS question, answered
      the assignment's own context-retention example ("Who was Alan
      Turing?" -> "What date was he born?" with no name repeated) using
      the same session's message history, and completed the full demo
      scenario end to end -- `write_file` -> `git_add` -> `git_commit`,
      all model-initiated tool calls, producing a real git commit -- via
      the official Filesystem and Git MCP servers.
- [x] Remote (HTTP + SSE) transport for the same server -- implemented,
      tested locally, and **deployed live** at
      `https://cc3067-lims-mcp.onrender.com` (Render, not Cloud Run --
      see "Difficulties" below). Verified against the real URL:
      `GET /health`, and a full `initialize` -> session handshake ->
      `tools/list` -> `tools/call` (success and not-found-error paths)
      sequence, all over real HTTPS.
- [x] Wireshark capture and JSON-RPC message classification -- done
      **twice**: once locally (loopback, plaintext,
      `docs/wireshark/local_capture.pcapng`) and once against the real
      deployed remote server (`docs/wireshark/remote_capture.pcapng`,
      real Ethernet frame, real IP routing, real TLS handshake), so the
      assignment's "servidor remoto" requirement is met with an actual
      remote capture, not just the local stand-in.

## 2. Wireshark / OSI-TCP-IP layer analysis (assignment item 9)

Full classification table, raw packet evidence, and the per-layer
explanation are in [`wireshark_analysis.md`](wireshark_analysis.md),
drawn from **two** real captures: one local (loopback, plaintext) and
one against the actual deployed remote server
(`https://cc3067-lims-mcp.onrender.com`, real network, real TLS).
Summary of the layer findings:

- **Link layer:** the local capture (Npcap loopback adapter) shows a
  `Null/Loopback` pseudo-header, not a real frame -- there's no
  link-layer hop when both endpoints are `127.0.0.1`. The remote capture
  (real Wi-Fi adapter) shows a genuine **Ethernet II** frame with real
  source/destination MAC addresses (the laptop's NIC and the home
  router), confirmed directly with `tshark -V`.
- **Network layer:** the local capture is `127.0.0.1 -> 127.0.0.1`
  (no real routing); the remote capture shows real IPv4 routing,
  `192.168.11.230` (the laptop, NATed by the router) ->
  `216.24.57.7` (Render's Cloudflare-fronted edge for
  `cc3067-lims-mcp.onrender.com`, confirmed with `nslookup`).
- **Transport layer:** both captures show the same pattern -- every one
  of the 7 JSON-RPC messages sent by `chatbot/mcp/http_client.py` opens
  its **own** TCP connection (no keep-alive reuse in `urllib`), each
  with its own 3-way handshake (`SYN`/`SYN, ACK`/`ACK`), confirmed by
  `tshark -z conv,tcp` on both files. One real difference: several
  remote connections close with a TCP `RST` rather than a graceful
  `FIN`, consistent with the CDN/proxy in front of Render tearing down
  short-lived `Connection: close` connections more aggressively than the
  local Python server does.
- **Application layer:** locally, three nested framings are directly
  readable in plaintext: HTTP (`POST /mcp`, status codes, the custom
  `Mcp-Session-Id` header) carrying SSE (`event: message` / `data: ...`)
  carrying JSON-RPC 2.0 (`"jsonrpc": "2.0"`, `id`/`method`/`result`). On
  the remote capture, `tshark -z io,phs` shows a **TLS** layer between
  TCP and where HTTP would be (59 of 130 frames): a real handshake
  (`ClientHello`/`ServerHello`) followed by every JSON-RPC byte traveling
  inside encrypted TLS Application Data records -- Wireshark can no
  longer show the HTTP/JSON-RPC content directly, only size, timing, and
  direction, which is the expected and correct outcome of deploying over
  HTTPS.

Message classification (full detail and raw bytes in
`wireshark_analysis.md`): `initialize` and `notifications/initialized`
are the protocol's **synchronization** messages (capability/session
handshake before real work starts); `tools/list` and every `tools/call`
are **requests**; the corresponding `result`/`error` bodies delivered
over SSE are the **responses** -- including the case where the *tool*
itself failed (`isError: true`), which is still a normal JSON-RPC
response, not a protocol-level error.

## 3. Conclusions (assignment item 10)

### Features implemented

A local MCP server (stdio) and a remote-transport MCP server (HTTP+SSE)
for a food-safety lab (LIMS) use case, both hand-implementing JSON-RPC
2.0 and the MCP method set (`initialize`, `notifications/initialized`,
`tools/list`, `tools/call`) with no SDK; a chatbot host that talks to
Anthropic's Messages API directly over HTTPS, keeps conversation context
across turns, orchestrates that server together with the official
Filesystem and Git MCP servers, and logs every MCP interaction; a real
live deployment of the remote server (`https://cc3067-lims-mcp.onrender.com`);
and two Wireshark captures (local and against that live deployment) with
a full message-classification and OSI/TCP-IP layer analysis of both.

### Difficulties encountered

- **Google Cloud Run required a billing account (credit card) before
  doing anything at all**, even to stay entirely within its free tier --
  there's no way around this on GCP's side, and it blocked the
  deployment the original proposal named. Resolved by deploying to
  [Render](https://render.com) instead: the assignment explicitly allows
  "Google Cloud, Cloudflare, etc.", Render's free web-service tier needs
  no card, and since `http_server.py` only relies on plain `HOST`/`PORT`
  environment variables rather than any Cloud-Run-specific API, the
  exact same `Dockerfile` deployed to Render completely unmodified --
  direct payoff of having kept the server's business logic and its
  hosting environment decoupled from the start. The one real tradeoff:
  Render's free instance sleeps after 15 minutes of inactivity (a 30-60s
  cold start on the next request), against Cloud Run's typically
  sub-second cold starts.
- **The published Git MCP server has no `git_init` tool.** Verified
  directly against `uvx mcp-server-git`'s `tools/list` response and its
  installed source (`git_status`, `git_diff*`, `git_commit`, `git_add`,
  `git_reset`, `git_log`, `git_create_branch`, `git_checkout`,
  `git_show`, `git_branch` is the complete list). The assignment's demo
  scenario explicitly asks the chatbot to "create a repository," which
  isn't possible through a tool that server doesn't expose. Resolved by
  having `chatbot/host.py` bootstrap an empty repository once at
  startup with a direct `git init` call, and letting the LLM do
  everything else (write the README, `git add`, `git commit`) through
  the actual MCP tools -- documented as a deliberate, disclosed
  workaround rather than hidden.
- **`npx`/`uvx` aren't directly executable from `subprocess.Popen` on
  Windows.** They're `.cmd`/`.exe` PATHEXT shims, and `Popen` without
  `shell=True` fails to resolve them via a plain `PATH` lookup
  (`WinError 2`). Fixed by resolving the command with `shutil.which()`
  first in `stdio_client.py`, which is PATHEXT-aware on Windows and a
  no-op on POSIX -- found and fixed by actually running the Filesystem
  and Git servers, not by inspection alone.
- **Claude's own replies crashed the console on Windows.** The default
  Windows terminal codepage (`cp1252`) can't encode arbitrary Unicode
  (checkmarks, emoji, some accented characters), and a plain `print()`
  of the model's text raised `UnicodeEncodeError`, killing the chatbot
  mid-conversation the first time a live response happened to include
  one. This only surfaces with real model output, not with any of the
  hand-authored test fixtures used earlier -- caught during the actual
  live demo run. Fixed by reconfiguring `sys.stdout`/`sys.stderr` to
  UTF-8 (`errors="replace"`) at the top of `chatbot/host.py`'s `main()`.
- **The Anthropic account had no usable balance at first**, even after
  creating an API key -- the assignment's promised free credit either
  wasn't applied or is no longer the default for new accounts, and the
  API returned a plain `400 invalid_request_error` ("credit balance is
  too low") rather than an auth failure. Resolved by adding a small
  amount of billing credit directly; Google's Gemini API (genuinely free
  with no card, verified separately) was evaluated as a fallback but not
  adopted, since the existing chatbot code is written specifically
  against Anthropic's Messages API shape and the actual cost for this
  project's usage is a few cents.
- **Two crash bugs only surfaced during the actual live demo run against
  the real deployment, not against any hand-authored test fixture:**
  1. The HTTP and stdio MCP clients each define their own `MCPError`
     class (same name, different types). `chatbot/host.py`'s tool-call
     error handling only imported and caught the stdio one, so an error
     from the HTTP client -- which is exactly what happens when Render's
     free instance recycles and forgets the chatbot's `Mcp-Session-Id`
     mid-conversation -- propagated uncaught and killed the entire
     chatbot process instead of being reported as a failed tool call.
  2. `chatbot/mcp/http_client.py`'s default request timeout (15s) was
     shorter than the 30-60s cold-start window `docs/deployment.md`
     itself documents for Render's free tier -- an internal
     inconsistency that made the very first connection attempt fail
     whenever the server had gone to sleep.

  Both were fixed the same evening they were found, live, hours before
  the presentation: the timeout was raised to a configurable default of
  60s, `run_tool()` now catches both client's error types plus a final
  broad `except Exception` so no single tool failure can ever bring down
  the whole session again, and -- since the root cause is a real,
  recurring characteristic of Render's free tier rather than a one-off
  -- a session-expiry case specifically triggers one automatic
  re-`initialize()` and retry before reporting failure, verified by
  deliberately corrupting a live session and confirming the chatbot
  recovered transparently.
- **Concurrent SQLite access under `ThreadingHTTPServer`.** The remote
  transport serves one thread per request, but the LIMS tools share one
  SQLite connection; a single lock around the shared protocol-dispatch
  call in `http_server.py` serializes access safely without complicating
  `tools.py` itself.
- **Reading the real captured bytes, not assuming the protocol's
  shape.** Rather than writing the Wireshark analysis from the spec
  alone, an actual local capture was taken and inspected with
  `tshark`, which surfaced a genuine, easy-to-miss detail: this
  project's HTTP client opens a new TCP connection per JSON-RPC message
  instead of reusing one -- a real characteristic of the implementation,
  not something a purely theoretical write-up would have caught.

### Lessons learned

- Keeping the protocol handlers (`protocol.py`) and business logic
  (`tools.py`, `database.py`) completely transport-agnostic made adding
  a second transport (HTTP + SSE) a genuinely small change -- the remote
  server is a new framing/dispatch shim, not a reimplementation, and it
  is guaranteed to behave identically to the local one because it calls
  the exact same `METHOD_HANDLERS` dispatch table.
- Designing the MCP client side (`chatbot/mcp/`) around one common
  interface (`initialize`, `call_tool`, `.tools`, `close`) meant the
  chatbot host never needs to know whether a given server is local
  (stdio) or remote (HTTP) -- switching is a one-line config change in
  `servers_config.json`, which is exactly what the assignment asks the
  chatbot to be able to do.
- Testing each transport directly (raw JSON-RPC over a pipe, `curl`
  against the HTTP endpoint, a real `tshark` capture) before wiring
  anything into the LLM loop caught real bugs (the Windows `Popen` issue,
  the missing `git_init` tool) that would have been much harder to
  diagnose from inside a live, non-deterministic LLM conversation.
- A capture against a real deployment surfaces things a local-only
  capture simply cannot: the local loopback capture never has a link
  layer to inspect and never touches TLS at all, so details like the
  real Ethernet framing, actual internet routing through the ISP/router,
  and the CDN in front of Render closing connections with `RST` instead
  of a graceful `FIN` only showed up once the traffic was captured
  against the live URL -- confirming it was worth deploying for real
  rather than treating the loopback capture as "close enough."
