"""Tests for response parsing in :mod:`track_aiops.bedrock_client`.

Covers the property-based guarantee that, for any valid Nova-family response
JSON, :meth:`BedrockClient._parse_response` produces a ``BedrockResponse``
whose ``text``, ``usage``, and ``stop_reason`` fields each match the
corresponding value in the source JSON, and whose token counts are
non-negative integers.

Property 2 (Response parsing extracts all fields correctly)
"""

import json
from io import BytesIO

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from track_aiops import bedrock_client
from track_aiops.bedrock_client import BedrockClient, BedrockResponse


class _FakeBody:
    """Minimal stand-in for the streaming body returned by ``invoke_model``.

    Exposes a ``read()`` method returning the response payload as bytes, which
    is exactly what :meth:`BedrockClient._parse_response` consumes.
    """

    def __init__(self, payload: bytes):
        self._stream = BytesIO(payload)

    def read(self) -> bytes:
        return self._stream.read()


@pytest.fixture
def client(monkeypatch):
    """A ``BedrockClient`` whose boto3 client is replaced with a dummy.

    Construction must not touch the network or require AWS credentials, so we
    patch ``boto3.client`` to return a trivial sentinel. Parsing does not use
    the boto3 client at all.
    """
    monkeypatch.setattr(bedrock_client.boto3, "client", lambda *a, **k: object())
    return BedrockClient(region="us-east-1", model_id="amazon.nova-pro-v1:0")


# Non-negative integer token counts, per the Nova ``usage`` schema.
token_counts = st.integers(min_value=0)

# A valid usage dict carrying the three documented token keys.
usage_strategy = st.fixed_dictionaries(
    {
        "inputTokens": token_counts,
        "outputTokens": token_counts,
        "totalTokens": token_counts,
    }
)


def _make_response(text: str, usage: dict, stop_reason: str) -> dict:
    """Wrap a valid Nova-family response JSON in a fake ``invoke_model`` result."""
    payload = {
        "output": {"message": {"content": [{"text": text}]}},
        "usage": usage,
        "stopReason": stop_reason,
    }
    return {"body": _FakeBody(json.dumps(payload).encode("utf-8"))}


@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    text=st.text(),
    usage=usage_strategy,
    stop_reason=st.text(),
)
def test_parse_response_extracts_all_fields(text, usage, stop_reason, client):
    """For any valid response JSON, each ``BedrockResponse`` field matches the
    source JSON value and token counts are non-negative integers.

    **Validates: Requirements 3.2**
    """
    response = _make_response(text, usage, stop_reason)

    result = client._parse_response(response)

    assert isinstance(result, BedrockResponse)
    # Each field round-trips the exact source value.
    assert result.text == text
    assert result.usage == usage
    assert result.stop_reason == stop_reason
    # Token counts remain non-negative integers (and never booleans).
    for key in ("inputTokens", "outputTokens", "totalTokens"):
        count = result.usage[key]
        assert isinstance(count, int) and not isinstance(count, bool)
        assert count >= 0


# --- Unit tests: explicit examples ------------------------------------------


def test_parse_response_typical_example(client):
    """A representative response parses into the expected ``BedrockResponse``."""
    usage = {"inputTokens": 12, "outputTokens": 34, "totalTokens": 46}
    response = _make_response("Hello, world!", usage, "end_turn")

    result = client._parse_response(response)

    assert result.text == "Hello, world!"
    assert result.usage == usage
    assert result.stop_reason == "end_turn"


def test_parse_response_zero_tokens(client):
    """Zero token counts are valid non-negative integers."""
    usage = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}
    response = _make_response("", usage, "")

    result = client._parse_response(response)

    assert result.usage == usage
    assert result.text == ""
    assert result.stop_reason == ""
