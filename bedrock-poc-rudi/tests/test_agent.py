"""
Unit tests for InvestigationAgent

Tests conversation loop, iteration counter, tool execution, RCA generation,
and termination conditions with mocked Bedrock and MCP clients.

Requirements: 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 6.1, 6.2
"""

import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agent import InvestigationAgent, InvestigationError, RCAReport, _utc_now
from src.bedrock_client import BedrockAuthError, BedrockResponse, BedrockResponseError, ToolUse
from src.config import AlertScenario
from src.mcp_client import MCPConnectionError, MCPToolResponse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _scenario(
    name: str = "Test Alert",
    description: str = "A test alert",
    initial_context: dict | str | None = None,
) -> AlertScenario:
    return AlertScenario(
        name=name,
        description=description,
        initial_context=initial_context or {"key": "value"},
        metadata={"severity": "high"},
    )


def _bedrock_response(
    text: str = "I will investigate.",
    stop_reason: str = "end_turn",
    tool_uses: list[ToolUse] | None = None,
) -> BedrockResponse:
    content = [{"text": text}]
    if tool_uses:
        for tu in tool_uses:
            content.append(
                {
                    "toolUse": {
                        "toolUseId": tu.tool_use_id,
                        "name": tu.name,
                        "input": tu.input,
                    }
                }
            )
    return BedrockResponse(
        message={"role": "assistant", "content": content},
        stop_reason=stop_reason,
        usage={"inputTokens": 100, "outputTokens": 50, "totalTokens": 150},
        tool_uses=tool_uses or [],
    )


def _mock_bedrock(responses: list[BedrockResponse]) -> Mock:
    client = Mock()
    client.format_message.side_effect = lambda role, content: {
        "role": role,
        "content": [{"text": content}] if isinstance(content, str) else content,
    }
    client.converse.side_effect = responses
    return client


def _mock_mcp(tool_result: MCPToolResponse | None = None) -> Mock:
    client = Mock()
    client.is_connected.return_value = True
    result = tool_result or MCPToolResponse(success=True, result="tool output")
    client.call_tool = AsyncMock(return_value=result)
    return client


def _make_agent(
    bedrock_client=None,
    mcp_client=None,
    max_iterations: int = 10,
) -> InvestigationAgent:
    return InvestigationAgent(
        bedrock_client=bedrock_client or _mock_bedrock([_bedrock_response()]),
        mcp_client=mcp_client or _mock_mcp(),
        max_iterations=max_iterations,
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInvestigationAgentInit:
    def test_stores_parameters(self):
        bedrock = Mock()
        mcp = Mock()
        agent = InvestigationAgent(
            bedrock_client=bedrock,
            mcp_client=mcp,
            max_iterations=5,
        )
        assert agent.bedrock_client is bedrock
        assert agent.mcp_client is mcp
        assert agent.max_iterations == 5
        assert agent.observability is None

    def test_default_max_iterations(self):
        agent = InvestigationAgent(Mock(), Mock())
        assert agent.max_iterations == 10


# ---------------------------------------------------------------------------
# Investigation flow
# ---------------------------------------------------------------------------


class TestInvestigationFlow:
    def test_natural_completion_returns_rca(self):
        bedrock = _mock_bedrock([_bedrock_response("Root cause found.", "end_turn")])
        agent = _make_agent(bedrock_client=bedrock)

        report = agent.investigate(_scenario())

        assert isinstance(report, RCAReport)
        assert "Root cause found." in report.investigation_summary
        assert report.iterations_used == 1

    def test_initial_user_message_contains_scenario_name(self):
        bedrock = _mock_bedrock([_bedrock_response()])
        agent = _make_agent(bedrock_client=bedrock)

        agent.investigate(_scenario(name="Checkout Error Spike"))

        first_call_messages = bedrock.converse.call_args.kwargs["messages"]
        first_message_text = str(first_call_messages)
        assert "Checkout Error Spike" in first_message_text

    def test_string_initial_context_is_included(self):
        bedrock = _mock_bedrock([_bedrock_response()])
        agent = _make_agent(bedrock_client=bedrock)

        agent.investigate(_scenario(initial_context="Error rate: 15%"))

        first_call_messages = bedrock.converse.call_args.kwargs["messages"]
        assert "Error rate: 15%" in str(first_call_messages)

    def test_dict_initial_context_is_json_serialized(self):
        bedrock = _mock_bedrock([_bedrock_response()])
        agent = _make_agent(bedrock_client=bedrock)

        agent.investigate(_scenario(initial_context={"error_rate": "15%"}))

        first_call_messages = bedrock.converse.call_args.kwargs["messages"]
        assert "error_rate" in str(first_call_messages)


# ---------------------------------------------------------------------------
# Iteration counter
# ---------------------------------------------------------------------------


class TestIterationCounter:
    def test_increments_monotonically(self):
        """Counter should be 1, 2, … for each Bedrock response."""
        tool_use = ToolUse(tool_use_id="tu-1", name="tool_a", input={})
        responses = [
            _bedrock_response("Thinking…", "tool_use", [tool_use]),
            _bedrock_response("Done.", "end_turn"),
        ]
        bedrock = _mock_bedrock(responses)
        agent = _make_agent(bedrock_client=bedrock)

        report = agent.investigate(_scenario())

        assert report.iterations_used == 2

    def test_respects_max_iterations(self):
        """Loop must terminate once max_iterations is reached."""
        tool_use = ToolUse(tool_use_id="tu-1", name="tool_a", input={})
        # Always return tool_use — would loop forever if counter not enforced
        bedrock = _mock_bedrock(
            [_bedrock_response("Still working…", "tool_use", [tool_use])] * 20
        )
        agent = _make_agent(bedrock_client=bedrock, max_iterations=3)

        report = agent.investigate(_scenario())

        assert report.iterations_used == 3
        assert bedrock.converse.call_count == 3

    def test_max_iterations_one(self):
        """Single-iteration budget terminates after first Bedrock call."""
        tool_use = ToolUse(tool_use_id="tu-1", name="tool_a", input={})
        bedrock = _mock_bedrock(
            [_bedrock_response("First pass.", "tool_use", [tool_use])] * 5
        )
        agent = _make_agent(bedrock_client=bedrock, max_iterations=1)

        report = agent.investigate(_scenario())

        assert report.iterations_used == 1


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------


class TestToolExecution:
    def test_tool_call_routed_to_mcp(self):
        tool_use = ToolUse(tool_use_id="tu-1", name="query_logs", input={"q": "error"})
        bedrock = _mock_bedrock(
            [
                _bedrock_response("Querying…", "tool_use", [tool_use]),
                _bedrock_response("Analysis complete.", "end_turn"),
            ]
        )
        mcp = _mock_mcp()
        agent = _make_agent(bedrock_client=bedrock, mcp_client=mcp)

        agent.investigate(_scenario())

        mcp.call_tool.assert_awaited_once_with("query_logs", {"q": "error"})

    def test_tool_result_appended_to_messages(self):
        """Second Bedrock call should include tool result in message history."""
        tool_use = ToolUse(tool_use_id="tu-1", name="get_metrics", input={})
        bedrock = _mock_bedrock(
            [
                _bedrock_response("Querying metrics.", "tool_use", [tool_use]),
                _bedrock_response("Done.", "end_turn"),
            ]
        )
        mcp = _mock_mcp(MCPToolResponse(success=True, result="metric data"))
        agent = _make_agent(bedrock_client=bedrock, mcp_client=mcp)

        agent.investigate(_scenario())

        second_call_messages = bedrock.converse.call_args_list[1].kwargs["messages"]
        # The user toolResult message should be in there
        assert any(
            "toolResult" in str(m) for m in second_call_messages
        ), "toolResult not found in second Bedrock call"

    def test_tool_failure_logs_and_continues(self):
        """A failing tool should log a warning and not abort the investigation."""
        tool_use = ToolUse(tool_use_id="tu-1", name="bad_tool", input={})
        bedrock = _mock_bedrock(
            [
                _bedrock_response("Using tool.", "tool_use", [tool_use]),
                _bedrock_response("Continuing despite error.", "end_turn"),
            ]
        )
        mcp = _mock_mcp(MCPToolResponse(success=False, error="Tool unavailable"))
        agent = _make_agent(bedrock_client=bedrock, mcp_client=mcp)

        report = agent.investigate(_scenario())

        # Investigation should complete (not abort)
        assert report.iterations_used == 2

    def test_multiple_tool_calls_all_executed(self):
        """All tool uses in a single response must be executed."""
        tool_uses = [
            ToolUse(tool_use_id=f"tu-{i}", name=f"tool_{i}", input={})
            for i in range(3)
        ]
        bedrock = _mock_bedrock(
            [
                _bedrock_response("Using multiple tools.", "tool_use", tool_uses),
                _bedrock_response("Done.", "end_turn"),
            ]
        )
        mcp = _mock_mcp()
        agent = _make_agent(bedrock_client=bedrock, mcp_client=mcp)

        agent.investigate(_scenario())

        assert mcp.call_tool.await_count == 3


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_bedrock_auth_error_terminates_investigation(self):
        bedrock = Mock()
        bedrock.format_message.side_effect = lambda role, content: {
            "role": role,
            "content": [{"text": content}],
        }
        bedrock.converse.side_effect = BedrockAuthError("Auth failed")
        agent = _make_agent(bedrock_client=bedrock)

        report = agent.investigate(_scenario())

        assert report.iterations_used == 0

    def test_bedrock_response_error_terminates_investigation(self):
        bedrock = Mock()
        bedrock.format_message.side_effect = lambda role, content: {
            "role": role,
            "content": [{"text": content}],
        }
        bedrock.converse.side_effect = BedrockResponseError("Bad response")
        agent = _make_agent(bedrock_client=bedrock)

        report = agent.investigate(_scenario())

        assert report.iterations_used == 0

    def test_mcp_connection_error_terminates_investigation(self):
        tool_use = ToolUse(tool_use_id="tu-1", name="tool", input={})
        bedrock = _mock_bedrock(
            [_bedrock_response("Calling tool.", "tool_use", [tool_use])]
        )
        mcp = Mock()
        mcp.is_connected.return_value = True
        mcp.call_tool = AsyncMock(side_effect=MCPConnectionError("Disconnected"))
        agent = _make_agent(bedrock_client=bedrock, mcp_client=mcp)

        report = agent.investigate(_scenario())

        # Should have run exactly 1 Bedrock call before MCP failure terminated it
        assert report.iterations_used == 1


# ---------------------------------------------------------------------------
# RCA generation
# ---------------------------------------------------------------------------


class TestRCAGeneration:
    def test_rca_attaches_blast_radius(self):
        bedrock = _mock_bedrock(
            [_bedrock_response("WHAT BROKE: N+1 in orders.py. WHAT IT COSTS: 42 customers.")]
        )
        agent = _make_agent(bedrock_client=bedrock)
        scenario = _scenario(
            name="Checkout Error",
            initial_context={
                "service": "checkout-service",
                "endpoint": "/api/checkout",
                "business_metrics": {
                    "stuck_customers": 42,
                    "financial_bleed_rate_usd_per_min": 145,
                },
                "suspected_technical_cause": "N+1 pattern in services/orders.py",
            },
        )

        report = agent.investigate(scenario)

        assert report.blast_radius is not None
        assert report.blast_radius.technical.status == "confirmed"
        assert report.blast_radius.business.affected_customers == 42
        assert report.blast_radius.business.financial_bleed_rate_usd_per_min == 145.0

    def test_initial_prompt_includes_blast_radius_context(self):
        bedrock = _mock_bedrock([_bedrock_response()])
        agent = _make_agent(bedrock_client=bedrock)
        scenario = _scenario(
            initial_context={
                "service": "checkout-service",
                "business_metrics": {"stuck_customers": 42, "financial_bleed_rate_usd_per_min": 145},
            },
        )

        agent.investigate(scenario)

        first_call_messages = bedrock.converse.call_args.kwargs["messages"]
        assert "BLAST RADIUS CONTEXT" in str(first_call_messages)

    def test_rca_contains_alert_name(self):
        bedrock = _mock_bedrock([_bedrock_response("Root cause: payment gateway.")])
        agent = _make_agent(bedrock_client=bedrock)

        report = agent.investigate(_scenario(name="Payment Failure"))

        assert report.alert_name == "Payment Failure"

    def test_rca_summary_from_last_assistant_message(self):
        responses = [_bedrock_response("The root cause is a memory leak.")]
        bedrock = _mock_bedrock(responses)
        agent = _make_agent(bedrock_client=bedrock)

        report = agent.investigate(_scenario())

        assert "memory leak" in report.investigation_summary

    def test_rca_includes_timestamp(self):
        bedrock = _mock_bedrock([_bedrock_response()])
        agent = _make_agent(bedrock_client=bedrock)

        report = agent.investigate(_scenario())

        assert "T" in report.timestamp  # ISO-8601 format check

    def test_rca_always_generated_on_max_iterations(self):
        """RCA must be produced even when budget is exhausted."""
        tool_use = ToolUse(tool_use_id="tu-1", name="tool", input={})
        bedrock = _mock_bedrock(
            [_bedrock_response("Still investigating.", "tool_use", [tool_use])] * 10
        )
        agent = _make_agent(bedrock_client=bedrock, max_iterations=2)

        report = agent.investigate(_scenario())

        assert isinstance(report, RCAReport)
        assert report.iterations_used == 2

    def test_rca_generated_on_early_termination(self):
        """RCA must be produced even on fatal Bedrock errors."""
        bedrock = Mock()
        bedrock.format_message.side_effect = lambda role, content: {
            "role": role,
            "content": [{"text": content}],
        }
        bedrock.converse.side_effect = BedrockAuthError("No creds")
        agent = _make_agent(bedrock_client=bedrock)

        report = agent.investigate(_scenario())

        assert isinstance(report, RCAReport)
        assert "terminated early" in report.investigation_summary

    def test_rca_key_findings_capped_at_ten(self):
        """No more than 10 findings should be extracted."""
        # Build 12 separate assistant messages
        responses = [
            _bedrock_response(f"Finding number {i}.", "tool_use", [
                ToolUse(tool_use_id=f"tu-{i}", name="tool", input={})
            ])
            for i in range(12)
        ]
        responses.append(_bedrock_response("Final summary.", "end_turn"))

        bedrock = _mock_bedrock(responses)
        agent = _make_agent(bedrock_client=bedrock, max_iterations=13)

        report = agent.investigate(_scenario())

        assert len(report.key_findings) <= 10


# ---------------------------------------------------------------------------
# Observability integration
# ---------------------------------------------------------------------------


class TestObservabilityIntegration:
    def test_trace_called_for_each_iteration(self):
        tool_use = ToolUse(tool_use_id="tu-1", name="tool", input={})
        responses = [
            _bedrock_response("Working…", "tool_use", [tool_use]),
            _bedrock_response("Done.", "end_turn"),
        ]
        bedrock = _mock_bedrock(responses)

        obs = Mock()
        obs.trace_bedrock_call.side_effect = lambda scenario_id, fn, **kwargs: fn(
            **kwargs
        )

        agent = InvestigationAgent(
            bedrock_client=bedrock,
            mcp_client=_mock_mcp(),
            observability=obs,
        )
        agent.investigate(_scenario())

        assert obs.trace_bedrock_call.call_count == 2

    def test_no_observability_still_works(self):
        bedrock = _mock_bedrock([_bedrock_response()])
        agent = InvestigationAgent(
            bedrock_client=bedrock,
            mcp_client=_mock_mcp(),
            observability=None,
        )
        report = agent.investigate(_scenario())
        assert isinstance(report, RCAReport)
