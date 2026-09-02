"""Minimal Anthropic Messages API client built on urllib (standard library
only -- no `anthropic` pip package).

The project intentionally talks to the LLM "at the API level" (assignment
objective #5) with raw HTTPS requests, the same way the MCP protocol
itself is implemented by hand instead of through an SDK.
"""
import json
import os
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 1024


class AnthropicError(Exception):
    """Raised for missing credentials or a non-2xx response from the API."""


class AnthropicClient:
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise AnthropicError(
                "ANTHROPIC_API_KEY is not set. Create a key at "
                "https://console.anthropic.com/ and export it (or put it in a "
                "local .env file) before running the chatbot."
            )
        self.model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)

    def create_message(self, messages, system=None, tools=None, max_tokens=DEFAULT_MAX_TOKENS):
        """Calls POST /v1/messages and returns the parsed JSON response."""
        body = {"model": self.model, "max_tokens": max_tokens, "messages": messages}
        if system:
            body["system"] = system
        if tools:
            body["tools"] = tools

        request = urllib.request.Request(
            API_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": API_VERSION,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8")
            raise AnthropicError(f"Anthropic API error {exc.code}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise AnthropicError(f"Could not reach the Anthropic API: {exc}") from exc
