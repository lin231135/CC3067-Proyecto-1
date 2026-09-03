# Deploying the LIMS MCP server to Google Cloud Run

This deploys the exact same server as `lims_mcp_server/http_server.py`
(same tools, same SQLite-backed logic) over the HTTP + SSE transport
described in the [README](../README.md#remote-transport-http--sse). It
requires a Google Cloud account and the `gcloud` CLI, so these steps must
be run by you, not by an assistant -- they need your own credentials.

## Prerequisites

1. A Google Cloud account and a project (Cloud Run's free tier is enough
   for this project's traffic).
2. [`gcloud` CLI installed](https://cloud.google.com/sdk/docs/install) and
   authenticated:
   ```bash
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   ```
3. Enable the required APIs (one time per project):
   ```bash
   gcloud services enable run.googleapis.com artifactregistry.googleapis.com
   ```

## 1. Build and deploy

From the repository root (where the `Dockerfile` lives):

```bash
gcloud run deploy lims-mcp-server \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080
```

`--source .` has Cloud Build build the `Dockerfile` in this repo and push
it to Artifact Registry automatically -- no manual `docker build`/`docker
push` needed. `--allow-unauthenticated` is used here because this is a
class demo with no sensitive data (synthetic lab samples only); a real
deployment would front this with proper authentication instead.

The command prints a **Service URL** when it finishes, e.g.:

```
https://lims-mcp-server-xxxxxxxxxx-uc.a.run.app
```

## 2. Verify it's up

```bash
curl https://YOUR-SERVICE-URL/health
# {"status": "ok", "server": "lims-food-analysis-mcp"}
```

## 3. Point the chatbot at it

Edit `chatbot/servers_config.json`:

```json
{
  "name": "lims-remote",
  "transport": "http",
  "enabled": true,
  "base_url": "https://YOUR-SERVICE-URL",
  ...
}
```

and set `"enabled": false` on the local `"lims"` entry so the chatbot
uses the remote copy instead (the assignment asks the chatbot to "use the
remote MCP server just like it uses the local one" -- since both clients
implement the same interface, this config flip is the only change
needed). Then run `python -m chatbot.host` as usual.

## 4. Capturing traffic with Wireshark

With the chatbot pointed at the Cloud Run URL, start a Wireshark capture
on your machine's active network interface **before** running the
chatbot, filtered to the service's traffic, e.g.:

```
host <the IP the Service URL resolves to> and tcp port 443
```

Since the connection is HTTPS, Wireshark will show the TLS handshake and
encrypted application data, not the JSON-RPC payloads in the clear --
this is expected and is itself worth noting in the report (see the
"What you'll actually see in Wireshark" note below). To inspect the
plaintext JSON-RPC messages as well, you have two options while
capturing for this assignment:

- Point the chatbot at the server running **locally** (`python -m
  lims_mcp_server.http_server`, no TLS) and capture on the loopback
  interface instead, filtered to `tcp port 8080` -- this shows the exact
  same Streamable HTTP + SSE messages, in the clear, that would otherwise
  be inside the Cloud Run TLS tunnel.
- Or export Wireshark's TLS decryption using `SSLKEYLOGFILE` if you want
  to decrypt the real remote HTTPS session (set the environment variable
  before running the chatbot, then load the key log file in Wireshark's
  TLS protocol preferences).

Full capture walkthrough and the JSON-RPC message classification
(sync/request/response) required by the assignment: see
[`docs/wireshark_analysis.md`](wireshark_analysis.md).

## Known limitations of this deployment

- **Ephemeral storage.** Cloud Run instances have an ephemeral
  filesystem; the SQLite database baked into the image at build time
  (`RUN python -m lims_mcp_server.seed` in the `Dockerfile`) resets to
  that same synthetic dataset on every fresh container instance (cold
  start, redeploy, or scale-to-zero). Any `register_sample` calls made
  during a session are not guaranteed to persist -- acceptable for this
  class project's demo purposes, but worth calling out explicitly rather
  than leaving it as a silent surprise.
- **No authentication.** `--allow-unauthenticated` is used purely to keep
  the demo simple; there is no sensitive data behind this server.
- **Single region, default scaling.** No specific scaling/region tuning
  was done beyond Cloud Run's defaults, since this only needs to serve a
  single developer's chatbot session for the assignment.
