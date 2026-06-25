"""
Unit tests for DDTraceWrapper

Tests APM span creation, tag/metric capture, and error marking with mocked
ddtrace tracer.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""

import sys
import os
from unittest.mock import MagicMock, Mock, patch, call

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.observability import DDTraceWrapper
from src.bedrock_client import BedrockResponse, ToolUse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bedrock_response(
    stop_reason: str = "end_turn",
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> BedrockResponse:
    return BedrockResponse(
        message={"role": "assistant", "content": [{"text": "ok"}]},
        stop_reason=stop_reason,
        usage={
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": input_tokens + output_tokens,
        },
        tool_uses=[],
    )


def _make_span() -> Mock:
    span = MagicMock()
    span.__enter__ = Mock(return_value=span)
    span.__exit__ = Mock(return_value=False)
    return span


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestDDTraceWrapperInit:
    def test_default_service_name(self):
        wrapper = DDTraceWrapper()
        assert wrapper.service_name == "incident-response-agent"

    def test_custom_service_name(self):
        wrapper = DDTraceWrapper(service_name="my-agent")
        assert wrapper.service_name == "my-agent"


# ---------------------------------------------------------------------------
# Span creation and tagging
# ---------------------------------------------------------------------------


class TestTraceBedrockCall:
    @patch("src.observability.tracer")
    def test_creates_bedrock_converse_span(self, mock_tracer):
        span = _make_span()
        mock_tracer.trace.return_value = span

        wrapper = DDTraceWrapper()
        fn = Mock(return_value=_bedrock_response())
        wrapper.trace_bedrock_call("scenario-1", fn, messages=[])

        mock_tracer.trace.assert_called_once_with(
            "bedrock.converse",
            service="incident-response-agent",
            resource="amazon.nova-micro-v1:0",
        )

    @patch("src.observability.tracer")
    def test_tags_scenario_id(self, mock_tracer):
        span = _make_span()
        mock_tracer.trace.return_value = span

        wrapper = DDTraceWrapper()
        fn = Mock(return_value=_bedrock_response())
        wrapper.trace_bedrock_call("checkout-errors", fn, messages=[])

        span.set_tag.assert_any_call("alert.scenario", "checkout-errors")

    @patch("src.observability.tracer")
    def test_tags_model_id(self, mock_tracer):
        span = _make_span()
        mock_tracer.trace.return_value = span

        wrapper = DDTraceWrapper()
        fn = Mock(return_value=_bedrock_response())
        wrapper.trace_bedrock_call("s1", fn, messages=[])

        span.set_tag.assert_any_call("model", "amazon.nova-micro-v1:0")

    @patch("src.observability.tracer")
    def test_tags_iteration_number(self, mock_tracer):
        span = _make_span()
        mock_tracer.trace.return_value = span

        wrapper = DDTraceWrapper()
        fn = Mock(return_value=_bedrock_response())
        wrapper.trace_bedrock_call("s1", fn, messages=[], iteration=3)

        span.set_tag.assert_any_call("iteration", 3)

    @patch("src.observability.tracer")
    def test_tags_stop_reason(self, mock_tracer):
        span = _make_span()
        mock_tracer.trace.return_value = span

        wrapper = DDTraceWrapper()
        fn = Mock(return_value=_bedrock_response(stop_reason="tool_use"))
        wrapper.trace_bedrock_call("s1", fn, messages=[])

        span.set_tag.assert_any_call("bedrock.stop_reason", "tool_use")


# ---------------------------------------------------------------------------
# Token metrics
# ---------------------------------------------------------------------------


class TestTokenMetrics:
    @patch("src.observability.tracer")
    def test_captures_input_tokens(self, mock_tracer):
        span = _make_span()
        mock_tracer.trace.return_value = span

        wrapper = DDTraceWrapper()
        fn = Mock(return_value=_bedrock_response(input_tokens=200))
        wrapper.trace_bedrock_call("s1", fn, messages=[])

        span.set_metric.assert_any_call("bedrock.input_tokens", 200)

    @patch("src.observability.tracer")
    def test_captures_output_tokens(self, mock_tracer):
        span = _make_span()
        mock_tracer.trace.return_value = span

        wrapper = DDTraceWrapper()
        fn = Mock(return_value=_bedrock_response(output_tokens=75))
        wrapper.trace_bedrock_call("s1", fn, messages=[])

        span.set_metric.assert_any_call("bedrock.output_tokens", 75)

    @patch("src.observability.tracer")
    def test_captures_total_tokens(self, mock_tracer):
        span = _make_span()
        mock_tracer.trace.return_value = span

        wrapper = DDTraceWrapper()
        fn = Mock(return_value=_bedrock_response(input_tokens=100, output_tokens=50))
        wrapper.trace_bedrock_call("s1", fn, messages=[])

        span.set_metric.assert_any_call("bedrock.total_tokens", 150)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @patch("src.observability.tracer")
    def test_marks_span_as_error_on_exception(self, mock_tracer):
        span = _make_span()
        mock_tracer.trace.return_value = span

        wrapper = DDTraceWrapper()
        fn = Mock(side_effect=RuntimeError("API down"))

        with pytest.raises(RuntimeError):
            wrapper.trace_bedrock_call("s1", fn, messages=[])

        span.set_tag.assert_any_call("error", True)

    @patch("src.observability.tracer")
    def test_captures_error_type_on_exception(self, mock_tracer):
        span = _make_span()
        mock_tracer.trace.return_value = span

        wrapper = DDTraceWrapper()
        fn = Mock(side_effect=ValueError("bad input"))

        with pytest.raises(ValueError):
            wrapper.trace_bedrock_call("s1", fn, messages=[])

        span.set_tag.assert_any_call("error.type", "ValueError")

    @patch("src.observability.tracer")
    def test_captures_error_message_on_exception(self, mock_tracer):
        span = _make_span()
        mock_tracer.trace.return_value = span

        wrapper = DDTraceWrapper()
        fn = Mock(side_effect=RuntimeError("Connection timeout"))

        with pytest.raises(RuntimeError):
            wrapper.trace_bedrock_call("s1", fn, messages=[])

        span.set_tag.assert_any_call("error.message", "Connection timeout")

    @patch("src.observability.tracer")
    def test_exception_is_re_raised(self, mock_tracer):
        span = _make_span()
        mock_tracer.trace.return_value = span

        wrapper = DDTraceWrapper()
        fn = Mock(side_effect=RuntimeError("fail"))

        with pytest.raises(RuntimeError, match="fail"):
            wrapper.trace_bedrock_call("s1", fn, messages=[])

    @patch("src.observability.tracer")
    def test_no_error_tags_on_success(self, mock_tracer):
        span = _make_span()
        mock_tracer.trace.return_value = span

        wrapper = DDTraceWrapper()
        fn = Mock(return_value=_bedrock_response())
        wrapper.trace_bedrock_call("s1", fn, messages=[])

        called_tags = [c.args[0] for c in span.set_tag.call_args_list]
        assert "error" not in called_tags


# ---------------------------------------------------------------------------
# Return value passthrough
# ---------------------------------------------------------------------------


class TestReturnValue:
    @patch("src.observability.tracer")
    def test_returns_fn_result(self, mock_tracer):
        span = _make_span()
        mock_tracer.trace.return_value = span

        expected = _bedrock_response()
        wrapper = DDTraceWrapper()
        fn = Mock(return_value=expected)

        result = wrapper.trace_bedrock_call("s1", fn, messages=[])

        assert result is expected

    @patch("src.observability.tracer")
    def test_forwards_kwargs_to_fn(self, mock_tracer):
        span = _make_span()
        mock_tracer.trace.return_value = span

        wrapper = DDTraceWrapper()
        fn = Mock(return_value=_bedrock_response())
        msgs = [{"role": "user", "content": [{"text": "hi"}]}]

        wrapper.trace_bedrock_call("s1", fn, messages=msgs)

        fn.assert_called_once_with(messages=msgs)
