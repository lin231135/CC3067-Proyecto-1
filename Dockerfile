# Container image for the remote (HTTP + SSE) deployment of the LIMS MCP
# server on Google Cloud Run. Only lims_mcp_server/ is needed here -- the
# chatbot host and its MCP client run on the developer's machine and talk
# to this container over the network.
FROM python:3.11-slim

WORKDIR /app
COPY lims_mcp_server/ ./lims_mcp_server/

# Bake a fixed, reproducible demo dataset into the image (same generator,
# same default seed, as the local server) so the remote server has
# realistic data to answer with as soon as it starts. Cloud Run's
# filesystem is ephemeral per instance, so this is regenerated on every
# fresh container instead of relying on a persisted volume.
RUN python -m lims_mcp_server.seed --samples 80

ENV HOST=0.0.0.0
# Cloud Run injects its own PORT at runtime and expects the container to
# listen on it; 8080 here is just the documented/local-testing default.
EXPOSE 8080

CMD ["python", "-m", "lims_mcp_server.http_server"]
