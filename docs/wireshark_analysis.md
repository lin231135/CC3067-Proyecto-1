# Wireshark analysis: chatbot &lt;-&gt; LIMS MCP server (HTTP + SSE)

This document satisfies assignment items #7 and #9: capturing every
interaction between the host and the MCP server, classifying which
JSON-RPC messages are synchronization, request, or response messages,
and explaining what happens at each OSI/TCP-IP layer.

## Two captures, one procedure

**What's here now** is a capture of the chatbot talking to the LIMS
server **running locally** (`python -m lims_mcp_server.http_server` on
`127.0.0.1:8080`), captured on Windows' Npcap loopback adapter with
`dumpcap`/`tshark` and committed at
[`docs/wireshark/local_capture.pcapng`](wireshark/local_capture.pcapng).
It exercises the exact same HTTP + SSE transport
([`lims_mcp_server/http_server.py`](../lims_mcp_server/http_server.py))
that runs on Cloud Run -- only the network path differs (loopback vs. the
real internet + TLS) -- so every JSON-RPC message shape, the session
handshake, and the classification below are representative of the real
remote traffic too.

**What the assignment additionally asks for** ("Análisis de la
comunicación entre el **servidor remoto** y el cliente") is a capture
against the actually-deployed Cloud Run instance. That requires your own
GCP deployment (see [`docs/deployment.md`](deployment.md)), so it has to
be captured by you. The procedure is identical to the one used here --
repeat the steps below against the deployed service, save the new
`.pcapng`, and redo the classification table with the real frame
numbers. Because Cloud Run terminates TLS, that capture will show an
encrypted TLS handshake and encrypted application data instead of
plaintext HTTP by default; see "Capturing the real remote traffic" below
for how to still see the JSON-RPC payloads.

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

- **Link layer.** This capture was taken on Npcap's loopback adapter, so
  Wireshark shows a **Null/Loopback** pseudo-header (`Encapsulation
  type: NULL/Loopback`, "Protocols in frame: `null:ip:tcp`") instead of
  a real link-layer frame -- loopback traffic never actually goes onto a
  wire or over the air, so there is no Ethernet/802.11 header, no MAC
  addresses, and no ARP. **A real capture against the deployed Cloud Run
  service would show a genuine Ethernet II frame** (source/destination
  MAC addresses of your NIC and default gateway) since that traffic
  really does leave the machine over its network interface.
- **Network layer (IP).** Every packet carries `Internet Protocol
  Version 4, Src: 127.0.0.1, Dst: 127.0.0.1` -- both endpoints are the
  same host, so routing is trivial (no gateway hop). `TTL=128` is the
  Windows default, `Don't Fragment` is set, and there's no fragmentation
  since every segment is well under the loopback MTU. Against the real
  remote server, this layer is where the actual routing across the
  internet to Cloud Run's IP happens, and the source address would be
  your machine's real (likely NATed) IP instead of `127.0.0.1`.
- **Transport layer (TCP).** Each of the 7 JSON-RPC messages rides its
  own TCP connection: a 3-way handshake (`SYN` -> `SYN, ACK` -> `ACK`,
  frames 1-3 for the first one), then the HTTP request/response
  segments (`PSH, ACK`), then a 4-way close (`FIN, ACK` from each side).
  TCP is what gives the JSON-RPC exchange reliable, in-order delivery
  over the connectionless IP layer below it -- this is also *why* HTTP
  (and therefore MCP's Streamable HTTP transport) is built on TCP rather
  than UDP: JSON-RPC messages must arrive complete and in order, or the
  JSON parsing in `http_server.py`/`http_client.py` would break. Against
  the real remote deployment, this same TCP handshake happens first,
  and then a **TLS handshake** happens on top of it before any HTTP
  bytes are sent (Cloud Run terminates HTTPS), which is the biggest
  structural difference from this local capture.
- **Application layer (HTTP + SSE + JSON-RPC).** This is where the
  actual MCP protocol lives, in three nested layers of framing: **HTTP**
  (`POST /mcp`, headers, status codes) carries **SSE** (`Content-Type:
  text/event-stream`, `event: message` / `data: ...` framing) which
  carries a **JSON-RPC 2.0** message (`{"jsonrpc": "2.0", "id": ...,
  "method"/"result": ...}`) as the `data:` payload. The `Mcp-Session-Id`
  header is MCP-specific application-layer state layered on top of
  plain HTTP, used to correlate the otherwise-stateless HTTP requests
  above into one logical MCP session.

## Capturing the real remote traffic

To get an equivalent capture against the actually-deployed Cloud Run
server for the final report:

1. Deploy per [`docs/deployment.md`](deployment.md) and get the Service
   URL.
2. Point `chatbot/servers_config.json`'s `lims-remote` entry at it and
   enable it (disable local `lims`).
3. Start a capture on your real network interface (not loopback),
   filtered to the Cloud Run host, e.g. `host <resolved-ip> and tcp port
   443`.
4. Run `python -m chatbot.host` and exercise the same tools as above.
5. You'll see a TLS handshake (`Client Hello` / `Server Hello` /
   certificate exchange) instead of plaintext HTTP, and the JSON-RPC
   payloads will be encrypted (`Application Data` records) -- this is
   expected and is itself the right thing to report: the same
   synchronization/request/response classification above still applies
   logically (you can still tell requests from responses by direction
   and timing, and TLS Application Data length), you just can't read the
   JSON bodies without decrypting the session (e.g. via
   `SSLKEYLOGFILE`, noted in `docs/deployment.md`).
