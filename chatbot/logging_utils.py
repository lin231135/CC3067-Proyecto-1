"""Structured logger for every MCP request/response the chatbot host sends.

Satisfies the assignment's requirement to maintain and display a log of
all interactions (requests and responses) with the MCP servers: entries
are kept in memory (for the host to display in the console) and mirrored
to data/logs/interactions.jsonl for later inspection.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_FILE = REPO_ROOT / "data" / "logs" / "interactions.jsonl"


class InteractionLogger:
    def __init__(self, echo=True, log_file=DEFAULT_LOG_FILE):
        self.echo = echo
        self.log_file = log_file
        self.entries = []
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(self, server_name, direction, message):
        """direction: 'request' | 'response' | 'notification'."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "server": server_name,
            "direction": direction,
            "message": message,
        }
        self.entries.append(entry)
        if self.log_file:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if self.echo:
            print(
                f"[mcp-log] {server_name} {direction}: {json.dumps(message, ensure_ascii=False)}",
                file=sys.stderr,
            )

    def dump(self):
        return list(self.entries)
