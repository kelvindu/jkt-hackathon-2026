"""Tests for malformed-response and auth-error rejection in
:mod:`track_aiops.bedrock_client`.

Covers:
- Malformed response bodies missing ``output.message.content[0].text`` or
  ``usage`` cause the parser to raise :class:`BedrockResponseError`
  (Property 3 — Malformed responses are rejected).
- An auth-related boto3 ``ClientError`` raised by ``invoke_model`` is
  translated into :class:`BedrockAuthError`, while a non-auth ``ClientError``
  propagates unchanged.

Property 3 (Malformed responses are rejected)
Validates: Requirements 3.3, 3.4
"""

import json

import pytest
from botocore.exceptions import ClientError
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from track_aiops import bedrock_client
from track_aiops.bedrock_client import (
    AUTH_ERROR_CODES,
    BedrockAuthError,
    BedrockClient,
    BedrockResponse,
    BedrockResponseError,
)

REGION = "us-east-1"
MODEL_ID = "amazon.nova-pro-v1:0"


# --- Test doubles -----------------------------------------------------------


class FakeBody:
    """Minimal stand-in for the streaming body returned by ``invoke_model``."""

    def __init__(self, payload):
        # ``payload`` may be a str/bytes (raw) or any object to serialize.
        if isinstance(payload, (bytes, bytearray, str)):
            self._raw = payload
        else:
            self._raw = json.dumps(payload)

    def read(self):
        return self._raw


class FakeBotoClient:
    """Dummy boto3 client whose ``invoke_model`` is configurable per test."""

    def __init__(self, *, raises=None, returns=None):
        self._raises = raises
        self._returns = returns
        self.calls = []

    def invoke_model(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._returns


@pytest.fixture
def patched_boto(monkeypatch):
    """Patch ``boto3.client`` so constructing a BedrockClient is side-effect free.

    Returns a setter that installs the FakeBotoClient the next constructed
    BedrockClient will receive.
    """
    holder = {"client": FakeBotoClient()}

    def fake_client(service_name, **kwargs):
        return holder["client"]

    monkeypatch.setattr(bedrock_client.boto3, "client", fake_client)

    def set_client(fake):
        holder["client"] = fake

    return set_client


def make_client(patched_boto, fake):
    """Install ``fake`` as the boto client and construct a BedrockClient."""
    patched_boto(fake)
    return BedrockClient(region=REGION, model_id=MODEL_ID)


def valid_result():
    """A fully-formed Nova-family response result dict."""
    return {
        "output": {"message": {"content": [{"text": "hello world"}]}},
        "usage": {"inputTokens": 3, "outputTokens": 2, "totalTokens": 5},
        "stopReason": "end_turn",
    }


def client_error(code):
    """Build a botocore ClientError carrying ``code``."""
    return ClientError(
        error_response={"Error": {"Code": code, "Message": f"{code} message"}},
        operation_name="InvokeModel",
    )


# --- Malformed response rejection (Requirement 3.4, Property 3) --------------


def drop_text(result):
    # Remove the text field so output.message.content[0].text is missing.
    result["output"]["message"]["content"][0] = {}
    return result


def drop_content(result):
    # Empty content list -> IndexError on content[0].
    result["output"]["message"]["content"] = []
    return result


def drop_usage(result):
    del result["usage"]
    return result


MALFORMERS = {
    "missing_text": drop_text,
    "empty_content": drop_content,
    "missing_usage": drop_usage,
}


@pytest.mark.parametrize("name", sorted(MALFORMERS))
def test_parse_rejects_missing_required_field(patched_boto, name):
    """A body missing text/content/usage raises BedrockResponseError."""
    client = make_client(patched_boto, FakeBotoClient())
    bad = MALFORMERS[name](valid_result())
    response = {"body": FakeBody(bad)}

    with pytest.raises(BedrockResponseError):
        client._parse_response(response)


@given(field=st.sampled_from(["text", "usage"]))
def test_parse_rejects_dropped_required_field_property(field):
    """Property 3: for any required field dropped, parsing is rejected.

    Generates which required field to remove and asserts the parser raises
    BedrockResponseError in every case.

    **Validates: Requirements 3.4**
    """
    # Build BedrockClient without touching boto3 by bypassing __init__.
    client = BedrockClient.__new__(BedrockClient)
    result = valid_result()
    if field == "text":
        result["output"]["message"]["content"][0] = {}
    else:
        del result["usage"]
    response = {"body": FakeBody(result)}

    with pytest.raises(BedrockResponseError):
        client._parse_response(response)


def test_parse_rejects_invalid_json(patched_boto):
    """A body that is not valid JSON raises BedrockResponseError."""
    client = make_client(patched_boto, FakeBotoClient())
    response = {"body": FakeBody("not-json{{{")}

    with pytest.raises(BedrockResponseError):
        client._parse_response(response)


def test_parse_rejects_unreadable_body(patched_boto):
    """A response with no readable body raises BedrockResponseError."""
    client = make_client(patched_boto, FakeBotoClient())

    with pytest.raises(BedrockResponseError):
        client._parse_response({})


def test_parse_accepts_valid_response(patched_boto):
    """Sanity check: a well-formed body parses into a BedrockResponse."""
    client = make_client(patched_boto, FakeBotoClient())
    response = {"body": FakeBody(valid_result())}

    parsed = client._parse_response(response)

    assert isinstance(parsed, BedrockResponse)
    assert parsed.text == "hello world"
    assert parsed.usage["totalTokens"] == 5
    assert parsed.stop_reason == "end_turn"


# --- Auth error translation (Requirement 3.3) -------------------------------


@pytest.mark.parametrize("code", sorted(AUTH_ERROR_CODES))
def test_invoke_translates_auth_client_error(patched_boto, code):
    """An auth-related ClientError from invoke_model becomes BedrockAuthError."""
    fake = FakeBotoClient(raises=client_error(code))
    client = make_client(patched_boto, fake)

    with pytest.raises(BedrockAuthError):
        client.invoke("hi")


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(code=st.sampled_from(sorted(AUTH_ERROR_CODES)))
def test_invoke_translates_any_auth_code_property(monkeypatch, code):
    """Property: every auth error code maps to BedrockAuthError."""
    fake = FakeBotoClient(raises=client_error(code))
    monkeypatch.setattr(bedrock_client.boto3, "client", lambda *a, **k: fake)
    client = BedrockClient(region=REGION, model_id=MODEL_ID)

    with pytest.raises(BedrockAuthError):
        client.invoke("hi")


def test_invoke_propagates_non_auth_client_error(patched_boto):
    """A non-auth ClientError is not swallowed — it propagates as ClientError."""
    fake = FakeBotoClient(raises=client_error("ThrottlingException"))
    client = make_client(patched_boto, fake)

    with pytest.raises(ClientError):
        client.invoke("hi")


def test_invoke_success_parses_response(patched_boto):
    """A successful invoke_model round-trips into a BedrockResponse."""
    fake = FakeBotoClient(returns={"body": FakeBody(valid_result())})
    client = make_client(patched_boto, fake)

    parsed = client.invoke("hi")

    assert isinstance(parsed, BedrockResponse)
    assert parsed.text == "hello world"
    # The Nova request body was sent with the expected model id.
    assert fake.calls[0]["modelId"] == MODEL_ID
