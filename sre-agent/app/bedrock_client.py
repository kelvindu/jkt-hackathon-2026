"""AWS Bedrock transport — Nova Pro via the Converse API with tool use.

Pure transport: this module has zero Datadog/ddtrace knowledge. Tracing wraps
it from the outside (see :mod:`app.observability`), keeping transport and
observability decoupled.

The Converse API is used (not ``invoke_model``) because it gives a uniform tool
schema (``toolConfig`` / ``toolUse`` / ``toolResult``) across Bedrock models,
which the multi-step agent loop depends on.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .config import MODEL_ID

# ClientError codes that mean "fix your credentials/region", not "retry".
AUTH_ERROR_CODES = frozenset(
    {
        "ExpiredTokenException",
        "UnrecognizedClientException",
        "AccessDeniedException",
        "InvalidSignatureException",
        "UnauthorizedException",
        "InvalidClientTokenId",
        "AuthFailure",
        "MissingAuthenticationToken",
        "SignatureDoesNotMatch",
    }
)


@dataclass
class ToolUse:
    """A tool call requested by the model."""

    tool_use_id: str
    name: str
    input: dict[str, Any]


@dataclass
class BedrockResponse:
    """Parsed Converse API response."""

    message: dict[str, Any]
    stop_reason: str
    usage: dict[str, int]
    tool_uses: list[ToolUse] = field(default_factory=list)

    @property
    def text(self) -> str:
        """Concatenated text blocks from the assistant message."""
        parts = [
            block["text"]
            for block in self.message.get("content", [])
            if isinstance(block, dict) and "text" in block
        ]
        return "\n".join(parts).strip()


class BedrockAuthError(Exception):
    """AWS rejected the request for auth/credential reasons."""


class BedrockResponseError(Exception):
    """Bedrock returned a malformed or unexpected response."""


class BedrockClient:
    """Thin wrapper over boto3 ``bedrock-runtime`` for the Converse API."""

    def __init__(self, region: Optional[str] = None, model_id: str = MODEL_ID) -> None:
        self.region = region or os.getenv("AWS_REGION", "us-east-1")
        self.model_id = model_id
        try:
            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        except (ClientError, BotoCoreError) as exc:  # pragma: no cover - boto rarely fails here
            raise BedrockAuthError(f"Failed to initialize Bedrock client: {exc}") from exc

    def converse(
        self,
        messages: list[dict[str, Any]],
        tool_config: Optional[dict[str, Any]] = None,
        system: Optional[str] = None,
        guardrail_config: Optional[dict[str, Any]] = None,
    ) -> BedrockResponse:
        """Send one conversation turn and return the parsed response.

        Args:
            messages: Bedrock-format message list.
            tool_config: Optional ``{"tools": [...]}`` advertising available tools.
            system: Optional system prompt (sent as the first system turn).
            guardrail_config: Optional ``guardrailConfig`` for Bedrock Guardrails.

        Raises:
            BedrockAuthError: On auth-related ClientError codes.
            BedrockResponseError: On any other API/parse failure.
        """
        kwargs: dict[str, Any] = {"modelId": self.model_id, "messages": messages}
        if tool_config:
            kwargs["toolConfig"] = tool_config
        if system:
            kwargs["system"] = [{"text": system}]
        if guardrail_config:
            kwargs["guardrailConfig"] = guardrail_config

        try:
            response = self._client.converse(**kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in AUTH_ERROR_CODES:
                raise BedrockAuthError(
                    f"AWS authentication failed ({code}). Check credentials and region "
                    f"(region={self.region!r})."
                ) from exc
            raise BedrockResponseError(f"Bedrock API error ({code}): {exc}") from exc
        except BotoCoreError as exc:
            raise BedrockResponseError(f"Bedrock transport error: {exc}") from exc

        return self._parse(response)

    @staticmethod
    def format_message(role: str, content: Any) -> dict[str, Any]:
        """Build a Bedrock message from a string / dict / list of content blocks."""
        if role not in ("user", "assistant"):
            raise ValueError(f"Invalid role: {role!r}. Must be 'user' or 'assistant'.")
        if isinstance(content, str):
            blocks = [{"text": content}]
        elif isinstance(content, dict):
            blocks = [content]
        elif isinstance(content, list):
            blocks = content
        else:
            raise ValueError(f"Invalid content type: {type(content)}.")
        return {"role": role, "content": blocks}

    def _parse(self, response: dict[str, Any]) -> BedrockResponse:
        try:
            message = response["output"]["message"]
        except (KeyError, TypeError) as exc:
            raise BedrockResponseError(
                f"Invalid Converse response (missing output.message): {response!r}"
            ) from exc

        stop_reason = response.get("stopReason", "unknown")
        usage = response.get("usage", {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0})
        return BedrockResponse(
            message=message,
            stop_reason=stop_reason,
            usage=usage,
            tool_uses=self._extract_tool_uses(message),
        )

    @staticmethod
    def _extract_tool_uses(message: dict[str, Any]) -> list[ToolUse]:
        tool_uses: list[ToolUse] = []
        for block in message.get("content", []):
            tu = block.get("toolUse") if isinstance(block, dict) else None
            if not tu:
                continue
            tool_use_id = tu.get("toolUseId", "")
            name = tu.get("name", "")
            if tool_use_id and name:
                tool_uses.append(ToolUse(tool_use_id, name, tu.get("input", {}) or {}))
        return tool_uses
