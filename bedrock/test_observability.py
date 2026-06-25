"""Tests for :mod:`track_aiops.observability`.

Covers span annotation completeness: for any prompt and BedrockResponse with
non-negative token counts, ``traced_llm`` must annotate the LLM span with
``input_data`` equal to the prompt, ``output_data`` equal to the response text,
and ``metrics`` matching the response usage.

Property 5 (Span annotation contains complete input, output, and metrics)
"""

from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st

from track_aiops import observability
from track_aiops.bedrock_client import BedrockResponse


class FakeBedrockClient:
    """Stub client whose ``invoke`` returns a preset :class:`BedrockResponse`.

    Lets the test drive ``traced_llm`` without any real boto3/AWS call.
    """

    def __init__(self, response: BedrockResponse):
        self._response = response

    def invoke(self, prompt: str) -> BedrockResponse:
        return self._response


# Non-negative token counts, per the property's precondition.
token_counts = st.integers(min_value=0, max_value=1_000_000)


# --- Property-based test (Property 5) ---------------------------------------


@given(
    prompt=st.text(),
    text=st.text(),
    input_tokens=token_counts,
    output_tokens=token_counts,
    total_tokens=token_counts,
)
def test_traced_llm_annotates_complete_input_output_and_metrics(
    prompt, text, input_tokens, output_tokens, total_tokens
):
    """``traced_llm`` annotates the span with the prompt, response text, and
    metrics matching the response usage.

    **Validates: Requirements 4.3**
    """
    usage = {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
    }
    response = BedrockResponse(text=text, usage=usage, stop_reason="end_turn")
    client = FakeBedrockClient(response)

    # Patch the imported LLMObs reference so ``annotate`` is an inspectable mock
    # and the call never reaches real Datadog. The ``@llm`` decorator remains a
    # safe no-op span wrapper that still runs the wrapped function.
    with patch.object(observability, "LLMObs") as mock_llmobs:
        result = observability.traced_llm(client, prompt)

    assert result is response

    mock_llmobs.annotate.assert_called_once()
    _, kwargs = mock_llmobs.annotate.call_args

    assert kwargs["input_data"] == prompt
    assert kwargs["output_data"] == text
    assert kwargs["metrics"] == {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


# --- enable_llmobs / flush behavior -----------------------------------------


def _make_settings() -> "object":
    """Construct a Settings instance with recognizable, distinct field values.

    Distinct values let the assertions confirm each argument is forwarded to
    ``LLMObs.enable`` from the matching ``Settings`` field (no cross-wiring).
    """
    from track_aiops.config import Settings

    return Settings(
        dd_api_key="test-api-key",
        dd_site="datadoghq.eu",
        dd_llmobs_ml_app="test-ml-app",
        aws_region="us-east-1",
        model_id="amazon.nova-pro-v1:0",
        model_name="nova-pro",
        model_provider="bedrock",
    )


def test_enable_llmobs_enables_agentless_with_correct_args(monkeypatch):
    """``enable_llmobs`` enables LLMObs once in agentless mode with the ml_app,
    API key, and site taken from settings.

    **Validates: Requirements 4.1**
    """
    # Reset the module-level idempotency guard so this case is deterministic.
    monkeypatch.setattr(observability, "_enabled", False)

    settings = _make_settings()

    with patch.object(observability, "LLMObs") as mock_llmobs:
        observability.enable_llmobs(settings)

    mock_llmobs.enable.assert_called_once_with(
        ml_app="test-ml-app",
        agentless_enabled=True,
        api_key="test-api-key",
        site="datadoghq.eu",
    )


def test_enable_llmobs_is_idempotent(monkeypatch):
    """Calling ``enable_llmobs`` multiple times enables LLMObs only once and
    never raises (idempotent enable).

    **Validates: Requirements 4.1, 4.4**
    """
    monkeypatch.setattr(observability, "_enabled", False)

    settings = _make_settings()

    with patch.object(observability, "LLMObs") as mock_llmobs:
        observability.enable_llmobs(settings)
        observability.enable_llmobs(settings)
        observability.enable_llmobs(settings)

    mock_llmobs.enable.assert_called_once()


def test_flush_delegates_to_llmobs(monkeypatch):
    """``flush`` forwards to ``LLMObs.flush`` exactly once.

    **Validates: Requirements 4.4**
    """
    with patch.object(observability, "LLMObs") as mock_llmobs:
        observability.flush()

    mock_llmobs.flush.assert_called_once_with()
