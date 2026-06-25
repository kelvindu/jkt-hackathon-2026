"""Property-based test for span annotation completeness in
:mod:`track_aiops.observability`.

Covers the guarantee that, for any prompt and :class:`BedrockResponse` with
non-negative token counts, :func:`traced_llm` annotates the LLM span with
``input_data`` equal to the prompt, ``output_data`` equal to the response
text, and ``metrics`` matching the response usage.

Property 5 (Span annotation contains complete input, output, and metrics)
"""

from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st

from track_aiops import observability
from track_aiops.bedrock_client import BedrockResponse


class FakeBedrockClient:
    """Stub client whose ``invoke`` returns a preset :class:`BedrockResponse`.

    Lets the test drive ``traced_llm`` without any real boto3/AWS network call.
    """

    def __init__(self, response: BedrockResponse):
        self._response = response
        self.invoked_with = None

    def invoke(self, prompt: str) -> BedrockResponse:
        self.invoked_with = prompt
        return self._response


# Non-negative integer token counts, per the property's precondition.
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
    """For any prompt and ``BedrockResponse`` with non-negative token counts,
    ``traced_llm`` annotates the span with ``input_data`` equal to the prompt,
    ``output_data`` equal to the response text, and ``metrics`` matching the
    response usage.

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
    # and the call never reaches real Datadog. The ``@llm`` decorator (applied
    # at import time) remains a safe no-op span wrapper that still runs the
    # wrapped function body.
    with patch.object(observability, "LLMObs") as mock_llmobs:
        result = observability.traced_llm(client, prompt)

    # The wrapped function still returns the underlying response unchanged.
    assert result is response
    assert client.invoked_with == prompt

    # The span is annotated exactly once with the complete payload.
    mock_llmobs.annotate.assert_called_once()
    _, kwargs = mock_llmobs.annotate.call_args

    assert kwargs["input_data"] == prompt
    assert kwargs["output_data"] == text
    assert kwargs["metrics"] == {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }
