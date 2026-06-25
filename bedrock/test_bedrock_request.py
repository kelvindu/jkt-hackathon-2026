"""Tests for request body construction in :mod:`track_aiops.bedrock_client`.

Covers the property-based guarantee that, for any prompt string,
:meth:`BedrockClient._build_body` produces a Nova-family request body whose
``messages[0].content[0].text`` equals the prompt and whose
``inferenceConfig.max_new_tokens`` equals 1024, and that the body serializes to
valid JSON that round-trips unchanged.

Property 1 (Request body construction preserves prompt and format)
"""

import json

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from track_aiops import bedrock_client
from track_aiops.bedrock_client import MAX_NEW_TOKENS, BedrockClient


@pytest.fixture
def client(monkeypatch):
    """A ``BedrockClient`` whose boto3 client is replaced with a dummy.

    Construction must not touch the network or require AWS credentials, so we
    patch ``boto3.client`` to return a trivial sentinel. Building the request
    body does not use the boto3 client at all.
    """
    monkeypatch.setattr(bedrock_client.boto3, "client", lambda *a, **k: object())
    return BedrockClient(region="us-east-1", model_id="amazon.nova-pro-v1:0")


@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(prompt=st.text())
def test_build_body_preserves_prompt_and_format(prompt, client):
    """For any prompt string, the body carries the exact prompt at
    ``messages[0].content[0].text``, sets ``inferenceConfig.max_new_tokens`` to
    1024, and serializes to valid JSON that round-trips unchanged.

    **Validates: Requirements 3.1, 3.5**
    """
    body = client._build_body(prompt)

    # The prompt is preserved verbatim in the documented location.
    assert body["messages"][0]["content"][0]["text"] == prompt
    # The token budget matches the module constant (1024).
    assert body["inferenceConfig"]["max_new_tokens"] == 1024

    # The body serializes to JSON and round-trips back to an equal dict,
    # confirming it is valid, serializable JSON.
    serialized = json.dumps(body)
    assert isinstance(serialized, str)
    assert json.loads(serialized) == body


# --- Unit tests: explicit examples ------------------------------------------


def test_build_body_typical_example(client):
    """A representative prompt builds the expected Nova request body."""
    body = client._build_body("What makes an AI system production-ready?")

    assert body == {
        "messages": [
            {
                "role": "user",
                "content": [{"text": "What makes an AI system production-ready?"}],
            }
        ],
        "inferenceConfig": {"max_new_tokens": MAX_NEW_TOKENS},
    }


def test_build_body_empty_prompt(client):
    """An empty prompt is preserved and the format is unchanged."""
    body = client._build_body("")

    assert body["messages"][0]["content"][0]["text"] == ""
    assert body["inferenceConfig"]["max_new_tokens"] == 1024
    assert json.loads(json.dumps(body)) == body
