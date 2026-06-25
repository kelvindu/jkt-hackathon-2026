"""Tests for :mod:`track_aiops.bedrock_client`.

Covers the Bedrock transport layer. This file currently holds the
request-body construction tests (Property 1); response-parsing and
error-handling tests are added by later tasks.

Property 1 (Request body construction preserves prompt and format)
"""

import json

from hypothesis import given, settings
from hypothesis import strategies as st

from track_aiops.bedrock_client import MAX_NEW_TOKENS, BedrockClient


def _build_body(prompt: str) -> dict:
    """Build a request body without touching AWS.

    ``BedrockClient.__init__`` constructs a real boto3 client, which we do not
    want during a pure-logic test. ``_build_body`` needs no client state, so we
    bypass ``__init__`` via ``__new__`` and call the method directly.
    """
    client = BedrockClient.__new__(BedrockClient)
    return client._build_body(prompt)


# --- Property-based test (Property 1) ---------------------------------------


@settings(max_examples=200)
@given(prompt=st.text())
def test_build_body_preserves_prompt_and_format(prompt):
    """For any prompt string, the constructed body embeds the prompt in the
    Nova message format, sets ``max_new_tokens`` to 1024, and is valid JSON.

    **Validates: Requirements 3.1, 3.5**
    """
    body = _build_body(prompt)

    # Prompt is preserved verbatim at the Nova message location.
    assert body["messages"][0]["content"][0]["text"] == prompt

    # max_new_tokens is fixed at 1024.
    assert body["inferenceConfig"]["max_new_tokens"] == 1024
    assert MAX_NEW_TOKENS == 1024

    # The body round-trips through JSON unchanged (i.e. is valid JSON).
    serialized = json.dumps(body)
    assert json.loads(serialized) == body
    assert json.loads(serialized)["messages"][0]["content"][0]["text"] == prompt


# --- Unit tests: explicit examples ------------------------------------------


def test_build_body_structure_for_simple_prompt():
    """A simple prompt produces the exact expected Nova request body."""
    body = _build_body("Hello")

    assert body == {
        "messages": [{"role": "user", "content": [{"text": "Hello"}]}],
        "inferenceConfig": {"max_new_tokens": 1024},
    }


def test_build_body_handles_empty_prompt():
    """An empty prompt is still embedded faithfully in the body."""
    body = _build_body("")

    assert body["messages"][0]["content"][0]["text"] == ""
    assert body["inferenceConfig"]["max_new_tokens"] == 1024


def test_build_body_handles_unicode_and_special_chars():
    """Unicode and JSON-special characters survive serialization."""
    prompt = 'quote " backslash \\ emoji 🚀 newline \n'
    body = _build_body(prompt)

    assert body["messages"][0]["content"][0]["text"] == prompt
    # Round-trips through JSON without corruption.
    assert json.loads(json.dumps(body))["messages"][0]["content"][0]["text"] == prompt


# ============================================================================
# Property 2 (Response parsing extracts all fields correctly)
# ============================================================================

import io

from track_aiops.bedrock_client import BedrockResponse


def _parse_response(raw_json: str) -> BedrockResponse:
    """Parse a raw JSON string without touching AWS.

    Wraps ``raw_json`` in a fake response object whose ``body.read()`` returns
    the JSON, mirroring boto3's ``invoke_model`` return shape, then calls
    ``_parse_response`` on a ``BedrockClient`` whose ``__init__`` is bypassed.
    """
    client = BedrockClient.__new__(BedrockClient)
    fake_response = {"body": io.BytesIO(raw_json.encode("utf-8"))}
    return client._parse_response(fake_response)


# Strategy: non-negative integers for token counts.
_token_counts = st.integers(min_value=0, max_value=10_000_000)


@st.composite
def _nova_response(draw):
    """Generate a valid Nova-family response payload and its source values.

    Returns a tuple of ``(payload_dict, expected_text, expected_usage,
    expected_stop_reason)`` so tests can assert the parsed fields match the
    exact values placed into the JSON.
    """
    text = draw(st.text())
    usage = {
        "inputTokens": draw(_token_counts),
        "outputTokens": draw(_token_counts),
        "totalTokens": draw(_token_counts),
    }
    stop_reason = draw(st.text())

    payload = {
        "output": {"message": {"content": [{"text": text}]}},
        "usage": usage,
        "stopReason": stop_reason,
    }
    return payload, text, usage, stop_reason


@settings(max_examples=200)
@given(data=_nova_response())
def test_parse_response_extracts_all_fields(data):
    """For any valid Nova response JSON, each parsed ``BedrockResponse`` field
    matches the source JSON value, and token counts are non-negative integers.

    **Validates: Requirements 3.2**
    """
    payload, expected_text, expected_usage, expected_stop_reason = data

    parsed = _parse_response(json.dumps(payload))

    # Each field round-trips from the source JSON unchanged.
    assert parsed.text == expected_text
    assert parsed.usage == expected_usage
    assert parsed.stop_reason == expected_stop_reason

    # Token counts are non-negative integers.
    for key in ("inputTokens", "outputTokens", "totalTokens"):
        count = parsed.usage[key]
        assert isinstance(count, int)
        assert count >= 0


# --- Unit tests: explicit examples ------------------------------------------


def test_parse_response_simple_example():
    """A representative Nova response parses into the expected fields."""
    payload = {
        "output": {"message": {"content": [{"text": "Hello there"}]}},
        "usage": {"inputTokens": 12, "outputTokens": 8, "totalTokens": 20},
        "stopReason": "end_turn",
    }

    parsed = _parse_response(json.dumps(payload))

    assert parsed.text == "Hello there"
    assert parsed.usage == {"inputTokens": 12, "outputTokens": 8, "totalTokens": 20}
    assert parsed.stop_reason == "end_turn"


def test_parse_response_zero_token_counts():
    """Zero token counts are valid non-negative integers and parse cleanly."""
    payload = {
        "output": {"message": {"content": [{"text": ""}]}},
        "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
        "stopReason": "end_turn",
    }

    parsed = _parse_response(json.dumps(payload))

    assert parsed.text == ""
    assert parsed.usage["inputTokens"] == 0
    assert parsed.usage["totalTokens"] == 0


# ============================================================================
# Property 3 (Malformed responses are rejected)
# ============================================================================

import pytest
from botocore.exceptions import ClientError

from track_aiops.bedrock_client import (
    AUTH_ERROR_CODES,
    BedrockAuthError,
    BedrockResponseError,
)


# --- Malformed response rejection (Requirement 3.3) -------------------------


@st.composite
def _malformed_payload(draw):
    """Generate a JSON payload that is missing at least one required field.

    Starts from a complete, valid Nova payload and deletes one or more of the
    required keys (the nested text, ``usage``, or ``stopReason``) so the parser
    is guaranteed to encounter a missing field.
    """
    payload = {
        "output": {"message": {"content": [{"text": draw(st.text())}]}},
        "usage": {
            "inputTokens": draw(_token_counts),
            "outputTokens": draw(_token_counts),
            "totalTokens": draw(_token_counts),
        },
        "stopReason": draw(st.text()),
    }

    # Choose a non-empty subset of fields to drop.
    drop_text = draw(st.booleans())
    drop_usage = draw(st.booleans())
    drop_stop = draw(st.booleans())
    # Ensure at least one field is dropped so the payload is truly malformed.
    if not (drop_text or drop_usage or drop_stop):
        drop_text = True

    if drop_text:
        # Empty the content list so content[0] raises IndexError.
        payload["output"]["message"]["content"] = []
    if drop_usage:
        del payload["usage"]
    if drop_stop:
        del payload["stopReason"]

    return payload


@settings(max_examples=200)
@given(payload=_malformed_payload())
def test_parse_response_rejects_malformed_payloads(payload):
    """Any JSON body missing a required field raises ``BedrockResponseError``.

    **Validates: Requirements 3.3**
    """
    with pytest.raises(BedrockResponseError):
        _parse_response(json.dumps(payload))


# --- Unit tests: explicit malformed examples --------------------------------


def test_parse_response_missing_text_raises():
    """A body missing ``output.message.content[0].text`` is rejected."""
    payload = {
        "output": {"message": {"content": []}},
        "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
        "stopReason": "end_turn",
    }
    with pytest.raises(BedrockResponseError):
        _parse_response(json.dumps(payload))


def test_parse_response_missing_usage_raises():
    """A body missing ``usage`` is rejected."""
    payload = {
        "output": {"message": {"content": [{"text": "hi"}]}},
        "stopReason": "end_turn",
    }
    with pytest.raises(BedrockResponseError):
        _parse_response(json.dumps(payload))


def test_parse_response_missing_stop_reason_raises():
    """A body missing ``stopReason`` is rejected."""
    payload = {
        "output": {"message": {"content": [{"text": "hi"}]}},
        "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
    }
    with pytest.raises(BedrockResponseError):
        _parse_response(json.dumps(payload))


def test_parse_response_invalid_json_raises():
    """A body that is not valid JSON is rejected."""
    with pytest.raises(BedrockResponseError):
        _parse_response("not valid json {{{")


def test_parse_response_unreadable_body_raises():
    """A response whose body has no ``read()`` is rejected."""
    client = BedrockClient.__new__(BedrockClient)
    with pytest.raises(BedrockResponseError):
        client._parse_response({"body": object()})


# --- Auth error rejection (Requirement 3.4) ---------------------------------


class _RaisingClient:
    """Stub boto3 client whose ``invoke_model`` raises a given exception."""

    def __init__(self, exc):
        self._exc = exc

    def invoke_model(self, **kwargs):
        raise self._exc


def _client_with_invoke_error(exc) -> BedrockClient:
    """Build a ``BedrockClient`` (bypassing boto3 init) wired to raise ``exc``.

    Sets the ``region`` and ``model_id`` attributes that ``invoke`` and
    ``_build_body`` reference, and replaces ``_client`` with a stub whose
    ``invoke_model`` raises ``exc``.
    """
    client = BedrockClient.__new__(BedrockClient)
    client.region = "us-east-1"
    client.model_id = "amazon.nova-pro-v1:0"
    client._client = _RaisingClient(exc)
    return client


def _make_client_error(code: str) -> ClientError:
    """Construct a boto3 ``ClientError`` carrying the given error ``code``."""
    return ClientError(
        {"Error": {"Code": code, "Message": "simulated failure"}},
        "InvokeModel",
    )


@settings(max_examples=200)
@given(code=st.sampled_from(sorted(AUTH_ERROR_CODES)))
def test_invoke_raises_auth_error_for_auth_codes(code):
    """Any auth-related ``ClientError`` code surfaces as ``BedrockAuthError``.

    **Validates: Requirements 3.4**
    """
    client = _client_with_invoke_error(_make_client_error(code))
    with pytest.raises(BedrockAuthError):
        client.invoke("hello")


def test_invoke_raises_auth_error_for_unrecognized_client():
    """An ``UnrecognizedClientException`` is mapped to ``BedrockAuthError``."""
    client = _client_with_invoke_error(
        _make_client_error("UnrecognizedClientException")
    )
    with pytest.raises(BedrockAuthError):
        client.invoke("hello")


def test_invoke_raises_auth_error_for_expired_token():
    """An ``ExpiredTokenException`` is mapped to ``BedrockAuthError``."""
    client = _client_with_invoke_error(_make_client_error("ExpiredTokenException"))
    with pytest.raises(BedrockAuthError):
        client.invoke("hello")


def test_invoke_propagates_non_auth_client_error():
    """A non-auth ``ClientError`` propagates unchanged, not as ``BedrockAuthError``."""
    client = _client_with_invoke_error(_make_client_error("ThrottlingException"))
    with pytest.raises(ClientError) as excinfo:
        client.invoke("hello")
    # It is the original ClientError, not a BedrockAuthError.
    assert not isinstance(excinfo.value, BedrockAuthError)
    assert excinfo.value.response["Error"]["Code"] == "ThrottlingException"
