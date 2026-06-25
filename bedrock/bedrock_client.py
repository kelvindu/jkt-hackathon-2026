"""AWS Bedrock transport layer for ``track_aiops``.

This module wraps boto3 ``bedrock-runtime`` calls behind a small, structured
interface. It builds the Nova-family request body, invokes the model, and
parses the response into a :class:`BedrockResponse`.

By design this module has **zero** Datadog/``ddtrace`` knowledge — it is pure
transport. Observability instrumentation lives in ``track_aiops.observability``
and wraps these calls from the outside, keeping transport and tracing decoupled.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 5.1
"""

from dataclasses import dataclass
from typing import Any

import json

import boto3
from botocore.exceptions import ClientError

# Maximum tokens the Nova model may generate per invocation.
MAX_NEW_TOKENS = 1024

# AWS ``ClientError`` codes that indicate an authentication/authorization or
# credential/region problem rather than a transient or server-side fault.
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
class BedrockResponse:
    """Structured result of a successful Bedrock model invocation.

    Attributes:
        text: The model's generated text, extracted from
            ``output.message.content[0].text``.
        usage: Token usage dict with keys ``inputTokens``, ``outputTokens``,
            and ``totalTokens``.
        stop_reason: The model's stop reason string (e.g. ``"end_turn"``).
    """

    text: str
    usage: dict
    stop_reason: str


class BedrockAuthError(Exception):
    """Raised when Bedrock rejects the request for auth/credential reasons.

    Indicates the caller should verify AWS credentials and the configured
    region rather than retrying as-is.
    """


class BedrockResponseError(Exception):
    """Raised when the Bedrock response body is malformed or missing fields.

    Indicates the response JSON did not match the expected Nova-family output
    structure, so the developer should inspect the raw body.
    """


class BedrockClient:
    """Thin wrapper over the boto3 ``bedrock-runtime`` client for Nova Pro."""

    def __init__(self, region: str, model_id: str):
        """Create the underlying boto3 ``bedrock-runtime`` client.

        Args:
            region: AWS region for the Bedrock runtime (e.g. ``us-east-1``).
            model_id: Bedrock model id (e.g. ``amazon.nova-pro-v1:0``).
        """
        self.region = region
        self.model_id = model_id
        self._client = boto3.client("bedrock-runtime", region_name=region)

    def _build_body(self, prompt: str) -> dict[str, Any]:
        """Build the Nova-family request body for ``prompt``.

        Args:
            prompt: The user prompt to send to the model.

        Returns:
            A dict matching the Nova request schema, with
            ``messages[0].content[0].text == prompt`` and
            ``inferenceConfig.max_new_tokens == 1024``.
        """
        return {
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {"max_new_tokens": MAX_NEW_TOKENS},
        }

    def invoke(self, prompt: str) -> BedrockResponse:
        """Invoke the model with ``prompt`` and return a structured response.

        Args:
            prompt: The user prompt to send to the model.

        Returns:
            A :class:`BedrockResponse` parsed from the model output.

        Raises:
            BedrockAuthError: If AWS rejects the request with an
                auth-related error code (bad credentials or region).
            BedrockResponseError: If the response body cannot be parsed into
                the expected Nova-family output structure.
        """
        body = self._build_body(prompt)

        try:
            response = self._client.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                body=json.dumps(body),
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in AUTH_ERROR_CODES:
                raise BedrockAuthError(
                    f"AWS authentication failed ({code}). "
                    "Check your AWS credentials and region "
                    f"(region={self.region!r})."
                ) from exc
            raise

        return self._parse_response(response)

    def _parse_response(self, response: Any) -> BedrockResponse:
        """Parse a raw ``invoke_model`` response into a :class:`BedrockResponse`.

        Args:
            response: The dict returned by boto3 ``invoke_model``.

        Returns:
            A populated :class:`BedrockResponse`.

        Raises:
            BedrockResponseError: If the body is not valid JSON or is missing
                any required field.
        """
        try:
            raw = response["body"].read()
        except (KeyError, AttributeError, TypeError) as exc:
            raise BedrockResponseError(
                f"Bedrock response missing readable body: {response!r}"
            ) from exc

        try:
            result = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise BedrockResponseError(
                f"Bedrock response body was not valid JSON: {raw!r}"
            ) from exc

        try:
            text = result["output"]["message"]["content"][0]["text"]
            usage = result["usage"]
            stop_reason = result["stopReason"]
        except (KeyError, IndexError, TypeError) as exc:
            raise BedrockResponseError(
                "Bedrock response missing expected fields "
                "(output.message.content[0].text, usage, stopReason): "
                f"{result!r}"
            ) from exc

        return BedrockResponse(text=text, usage=usage, stop_reason=stop_reason)
