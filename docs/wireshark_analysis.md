# Wireshark analysis: chatbot &lt;-&gt; LIMS MCP server (HTTP + SSE)

This document satisfies assignment items #7 and #9: capturing every
interaction between the host and the MCP server, classifying which
JSON-RPC messages are synchronization, request, or response messages,
and explaining what happens at each OSI/TCP-IP layer.

## Two captures

Two full captures of the same 7-message exchange (`initialize` ->
`notifications/initialized` -> `tools/list` -> 4x `tools/call`) were
taken and are both committed here, on purpose, as a side-by-side
comparison:

1. **[`local_capture.pcapng`](wireshark/local_capture.pcapng)** -- the
   chatbot talking to the LIMS server **running locally**
   (`python -m lims_mcp_server.http_server` on `127.0.0.1:8080`),
   captured on Windows' Npcap loopback adapter. Plaintext HTTP, so every
   JSON-RPC byte is directly visible -- this is the one the detailed
   frame-by-frame evidence below is drawn from.
2. **[`remote_capture.pcapng`](wireshark/remote_capture.pcapng)** -- the
   same exchange, this time against the **actually-deployed remote
   server** ("Análisis de la comunicación entre el servidor remoto y el
   cliente", per the assignment): `https://cc3067-lims-mcp.onrender.com`
   (see [`docs/deployment.md`](deployment.md) for why Render instead of
   Cloud Run), captured on the machine's real Wi-Fi interface. This one
   is real HTTPS -- a genuine Ethernet frame, real routing, and a TLS
   handshake in front of the same JSON-RPC exchange, which the "Local vs.
   remote" section below compares directly against capture #1.

Both were produced with the exact same driver script (a plain Python
snippet using `chatbot/mcp/http_client.py`), so the only variable
between them is local-plaintext vs. remote-TLS.

## How this capture was produced

```bash
# 1. Start a capture on the loopback adapter, filtered to the server's port
dumpcap -i "Adapter for loopback traffic capture" -f "tcp port 8080" -w local_capture.pcapng

# 2. In another terminal, run the LIMS server
python -m lims_mcp_server.http_server

# 3. In a third terminal, exercise it exactly like the chatbot host does:
#    initialize -> notifications/initialized -> tools/list -> four tools/call
#    (list_pending_samples, get_sample_status success, get_sample_status
#    not-found error, register_sample)
python -m chatbot.host   # or drive chatbot/mcp/http_client.py directly

# 4. Stop the capture, then open it in Wireshark or inspect it with tshark
```

On Windows, `npx`/`uvx`-style PATH issues aside, the one thing worth
knowing if you repeat this: Python's `urllib.request` (used by
`chatbot/mcp/http_client.py`) does **not** reuse TCP connections across
separate `urlopen()` calls -- every JSON-RPC message in this project
opens a brand-new TCP connection (visible below as 7 separate
`tcp.stream` values for 7 messages, each with its own 3-way handshake).
This is a legitimate, real characteristic of this project's traffic
worth reporting, not a capture artifact.

## Message classification

Every one of the 7 JSON-RPC messages sent in this capture, and which
category it belongs to:

| # | `tcp.stream` | JSON-RPC method | Category | HTTP | Has `id`? |
|---|---|---|---|---|---|
| 1 | 0 | `initialize` (request) | **Synchronization** (session/capability handshake) | `POST /mcp` → `200`, `text/event-stream` | yes (`1`) |
| 2 | 1 | `notifications/initialized` | **Synchronization** (handshake completion notice) | `POST /mcp` → `202 Accepted`, empty body | no (notification) |
| 3 | 2 | `tools/list` | **Request** | `POST /mcp` → `200`, `text/event-stream` | yes (`2`) |
| 4 | 3 | `tools/call` (`list_pending_samples`) | **Request** | `POST /mcp` → `200`, `text/event-stream` | yes (`3`) |
| 5 | 4 | `tools/call` (`get_sample_status`, found) | **Request** | `POST /mcp` → `200`, `text/event-stream` | yes (`4`) |
| 6 | 5 | `tools/call` (`get_sample_status`, not found) | **Request** | `POST /mcp` → `200`, `text/event-stream` | yes (`5`) |
| 7 | 6 | `tools/call` (`register_sample`) | **Request** | `POST /mcp` → `200`, `text/event-stream` | yes (`6`) |

And the **response** half of each: every SSE `event: message` frame
inside an HTTP `200` response (streams 0, 2-6) is the JSON-RPC
**response** to that stream's request -- e.g. stream 5's response
carries `"result": {"content": [...], "isError": true}`, which is a
normal JSON-RPC *response* even though the tool call itself failed (see
[`docs/lims_mcp_server_spec.md`](lims_mcp_server_spec.md) on tool errors
vs. protocol errors). The `202 Accepted` on stream 1 is **not** a
JSON-RPC response at all -- notifications never get one, per JSON-RPC
2.0; `202` is purely an HTTP-level acknowledgement that the byte stream
was received.

**Why `initialize` + `notifications/initialized` count as
"synchronization"**: per the MCP specification, these two messages are
the *initialization phase* -- the client and server exchange protocol
versions and capabilities and agree they're ready to proceed, before any
real tool traffic happens. Everything after that point (`tools/list`,
`tools/call`) is ordinary request/response traffic. This mirrors, one
layer up, exactly what TCP's own three-way handshake (`SYN` /
`SYN, ACK` / `ACK`) does at the transport layer for every one of these 7
connections -- see the packet evidence below.

### Raw evidence: `initialize` (stream 0, synchronization)

```
Frame 1  127.0.0.1:52136 -> 127.0.0.1:8080  TCP [SYN] Seq=0
Frame 2  127.0.0.1:8080  -> 127.0.0.1:52136 TCP [SYN, ACK] Seq=0 Ack=1
Frame 3  127.0.0.1:52136 -> 127.0.0.1:8080  TCP [ACK] Seq=1 Ack=1

Frame 6  POST /mcp HTTP/1.1
         Content-Type: application/json
         Connection: close

         {"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                      "clientInfo": {"name": "cc3067-chatbot-host", "version": "1.0.0"}}}

Frame 10 HTTP/1.0 200 OK
         Content-Type: text/event-stream
         Mcp-Session-Id: c76c891d05134ced8325fe4f99180a3a

         event: message
         data: {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18",
                "capabilities": {"tools": {"listChanged": false}},
                "serverInfo": {"name": "lims-food-analysis-mcp", "version": "1.0.0"}, ...}}
```

### Raw evidence: `notifications/initialized` (stream 1, synchronization, no response)

```
Frame 21 POST /mcp HTTP/1.1
         Mcp-Session-Id: c76c891d05134ced8325fe4f99180a3a

         {"jsonrpc": "2.0", "method": "notifications/initialized"}

Frame 23 HTTP/1.0 202 Accepted
         Content-Length: 0
```

### Raw evidence: `tools/call` error case (stream 5, request + response)

```
Frame 79 POST /mcp HTTP/1.1
         Mcp-Session-Id: c76c891d05134ced8325fe4f99180a3a

         {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
          "params": {"name": "get_sample_status", "arguments": {"sample_code": "DOES-NOT-EXIST"}}}

Frame 83 HTTP/1.0 200 OK
         Content-Type: text/event-stream

         event: message
         data: {"jsonrpc": "2.0", "id": 5,
                "result": {"content": [{"type": "text", "text": "Sample 'DOES-NOT-EXIST' was not found."}],
                           "isError": true}}
```

Note this is a **JSON-RPC response** (has `"result"`) even though the
*tool* failed -- exactly the "tool errors vs. protocol errors" design
decision documented in the main spec.

## Capture summary

```
Protocol Hierarchy Statistics (tshark -z io,phs)
frame  103 frames, 16396 bytes
  null (loopback pseudo-header)
    ip
      tcp    103 frames, 16396 bytes
        http  14 frames (7 requests + 7 responses)
          json   7 frames  (the application/json request bodies)
          media  6 frames  (the text/event-stream response bodies; the
                             7th response, the 202 to the notification,
                             has no body)

TCP Conversations (tshark -z conv,tcp): 7 independent connections,
one per JSON-RPC message (52136-52142 <-> 8080), each ~13-15 frames:
SYN, SYN-ACK, ACK, PSH/ACK (request), ACK, PSH/ACK (response), ACK,
then a FIN/ACK exchange in both directions to close.
```

## OSI / TCP-IP layer explanation

Based directly on the packets above (frame 1, expanded with `tshark -V`,
is the worked example):

- **Link layer.** The **local** capture was taken on Npcap's loopback
  adapter, so Wireshark shows a **Null/Loopback** pseudo-header
  (`Encapsulation type: NULL/Loopback`, "Protocols in frame:
  `null:ip:tcp`") instead of a real link-layer frame -- loopback traffic
  never actually goes onto a wire or over the air, so there is no
  Ethernet/802.11 header, no MAC addresses, and no ARP. The **remote**
  capture, taken on the real Wi-Fi adapter, shows exactly what that
  local capture couldn't: a genuine **Ethernet II** frame,
  `Src: AzureWaveTec_b1:8f:d7 (70:66:55:b1:8f:d7)` (the laptop's Wi-Fi
  NIC) `Dst: BaoanGaokeEl_28:a2:d5 (00:16:78:28:a2:d5)` (the home
  router's MAC) -- confirmed directly from `tshark -V` on frame 1 of
  `remote_capture.pcapng`.
- **Network layer (IP).** The local capture is `127.0.0.1 -> 127.0.0.1`
  (same host, no real routing). The remote capture shows real IPv4
  routing: `192.168.11.230` (the laptop's private LAN address) ->
  `216.24.57.7` (Render's edge, actually a Cloudflare-fronted address
  for `cc3067-lims-mcp.onrender.com` -- confirmed with `nslookup`, which
  resolved the hostname through `*.cdn.cloudflare.net`). The private
  source address is NATed by the home router before reaching the public
  internet, which Wireshark on the client side can't show directly (that
  translation happens on the router, past this capture point).
- **Transport layer (TCP).** Both captures show the same underlying
  pattern: **7 independent TCP connections**, one per JSON-RPC message
  (`chatbot/mcp/http_client.py`'s `urllib` calls don't reuse
  connections), each with its own 3-way handshake (`SYN` -> `SYN, ACK`
  -> `ACK`). `tshark -z conv,tcp` on the remote capture confirms exactly
  7 conversations to `216.24.57.7:443` (plus one short 2-frame outlier to
  a second Cloudflare edge IP, `216.24.57.15`, from a connection that got
  redirected to a different edge node). The one structural difference:
  several of the remote connections end in a **TCP `RST`** rather than a
  clean `FIN`/`FIN,ACK` exchange (visible in `remote_capture.pcapng`,
  e.g. frame 17) -- consistent with the CDN/proxy in front of Render
  aggressively tearing down short-lived HTTP/1.0 `Connection: close`
  connections instead of waiting out a graceful 4-way close, something
  the local Python `http.server` never does. TCP is what gives the
  JSON-RPC exchange reliable, in-order delivery over the connectionless
  IP layer below it either way -- this is also *why* HTTP (and therefore
  MCP's Streamable HTTP transport) is built on TCP rather than UDP:
  JSON-RPC messages must arrive complete and in order, or the JSON
  parsing in `http_server.py`/`http_client.py` would break.
- **Application layer (HTTP + SSE + JSON-RPC, plus TLS on the remote
  path).** Locally, this is three nested framings: **HTTP** (`POST
  /mcp`, headers, status codes) carries **SSE** (`Content-Type:
  text/event-stream`, `event: message` / `data: ...`) carries **JSON-RPC
  2.0** (`{"jsonrpc": "2.0", "id": ..., "method"/"result": ...}`) as the
  `data:` payload -- all readable in plaintext, as shown in the raw
  evidence above. On the remote path, `tshark -z io,phs` on
  `remote_capture.pcapng` shows a **`tls`** layer sitting between TCP and
  where HTTP would be (59 of 130 frames, 40444 of 47167 bytes): a real
  **TLS handshake** (`ClientHello` -> `ServerHello` -> certificate ->
  `ChangeCipherSpec`, record content types `22`/`20` in the capture)
  happens first, and every JSON-RPC byte after that travels inside
  encrypted **TLS Application Data** records instead of a plaintext HTTP
  body -- Wireshark cannot show the `POST /mcp` line or the JSON itself
  for this capture, only that *some* request went out and *some*
  response came back, with what size and timing. The `Mcp-Session-Id`
  header is MCP-specific application-layer state layered on top of HTTP
  either way, correlating otherwise-stateless requests into one logical
  MCP session -- it's just additionally encrypted on the remote path.

## Local vs. remote, side by side

| | Local (`local_capture.pcapng`) | Remote (`remote_capture.pcapng`) |
|---|---|---|
| Target | `127.0.0.1:8080` | `cc3067-lims-mcp.onrender.com` (`216.24.57.7:443`) |
| Capture interface | Npcap loopback adapter | Wi-Fi (real NIC) |
| Link layer | Null/Loopback pseudo-header | Real Ethernet II, real MAC addresses |
| Network layer | `127.0.0.1 -> 127.0.0.1` | `192.168.11.230 -> 216.24.57.7`, real internet routing |
| Security | None (plaintext) | TLS (`ClientHello`/`ServerHello`, encrypted Application Data) |
| JSON-RPC visible in Wireshark? | Yes, directly | No -- encrypted; only size/timing/direction are visible without decrypting the session |
| TCP connections | 7 (one per message), clean `FIN` closes | 7 (one per message) + 1 outlier, some closed with `RST` instead of `FIN` |
| Total frames / bytes | 103 frames / 16,396 bytes | 130 frames / 47,167 bytes (TLS overhead) |

The synchronization/request/response classification from the section
above is identical on both -- it's a property of the JSON-RPC/MCP
message sequence, not of the transport security wrapping it. What
changes between them is exactly what you'd expect from adding TLS and a
real network hop: a handshake before anything else, more bytes on the
wire, and the payload itself becoming opaque to a passive observer --
which is, in fact, the entire point of deploying this over HTTPS instead
of plain HTTP.
