"""
Conversation loop and investigation orchestration module.

Implements the core InvestigationAgent that manages the Bedrock ↔ MCP tool loop,
enforces iteration budget, and generates RCA reports.

ENHANCED: Integrated with Datadog LLM Observability for agent monitoring.

Requirements: 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 6.1, 6.2
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Optional

from .bedrock_client import (
    BedrockAuthError,
    BedrockClient,
    BedrockResponse,
    BedrockResponseError,
    ToolUse,
)
from .config import AlertScenario
from .git_tools import GIT_TOOL_CONFIG, GIT_TOOL_NAMES, execute_git_tool
from .blast_radius import (
    BlastRadiusCalculator,
    BlastRadiusReport,
    format_blast_radius_card,
    format_blast_radius_context,
)
from .mcp_client import MCPClient, MCPConnectionError

# LLM Observability SDK for agent monitoring
try:
    from ddtrace.llmobs import LLMObs
    LLMOBS_AVAILABLE = True
except ImportError:
    LLMOBS_AVAILABLE = False

if TYPE_CHECKING:
    from .observability import DDTraceWrapper

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an autonomous Site Reliability Engineering (SRE) agent. \
Your mission is to investigate production alerts, identify the root cause, and — \
when the root cause is in application code — fix it automatically and submit a Pull Request.

## Investigation workflow

1. Start by querying Datadog observability data (logs, metrics, traces) using the \
   available Datadog tools to understand what is happening at the infrastructure level.

2. If your analysis reveals an APPLICATION-LEVEL root cause — such as:
   - N+1 database queries
   - Missing or incorrect HTTP timeouts
   - Unbounded loops or list operations
   - Incorrect retry logic
   - Missing error handling
   - Memory leaks
   - Thread/connection pool exhaustion caused by code

   then you MUST use the read_application_code tool to read the relevant source file \
   and examine the exact code.

3. After reading the code, rewrite the fixed version entirely in your reasoning. \
   Produce correct, production-ready Python (or whatever language the file uses) that \
   resolves the bug.

4. Call create_github_pr with:
   - The full corrected file content (not a diff — the complete replacement)
   - A clear commit message in the imperative mood (e.g. "Fix missing timeout in orders fetch")
   - A descriptive PR title
   - A PR body that explains the root cause, what you changed, and why

5. In your FINAL Root Cause Analysis summary you MUST use this exact structure:

   WHAT BROKE: [confirmed root cause, file, bug pattern]
   WHAT IT COSTS: [use pre-computed customer count and $/min from BLAST RADIUS CONTEXT — do NOT invent dollar amounts]
   RECOMMENDED ACTION: [runbook + savings + Fix PR URL if created]

   Also include:
   - Which file and lines contained the bug
   - The PR URL returned by create_github_pr (format it as: "Fix PR: <url>")
   - Confidence level

## Important rules
- Only call create_github_pr AFTER you have read the file with read_application_code.
- Do NOT fabricate PR URLs. Only use the URL returned by the tool.
- If create_github_pr fails, report the error in your RCA and still provide the \
  corrected code inline in the summary so engineers can apply it manually.
- Keep investigations focused. Use Datadog tools to confirm the root cause first, \
  then move to code investigation only when warranted.
"""


@dataclass
class RCAReport:
    """
    Root Cause Analysis report generated at investigation completion.

    Attributes:
        alert_name: Name of the investigated alert
        investigation_summary: Final summary from the LLM
        key_findings: Individual findings extracted from conversation history
        iterations_used: Number of Bedrock converse turns consumed
        timestamp: ISO-8601 UTC timestamp of report creation
        blast_radius: Unified technical + business impact report (optional)
    """

    alert_name: str
    investigation_summary: str
    key_findings: list[str]
    iterations_used: int
    timestamp: str
    blast_radius: Optional[BlastRadiusReport] = None


@dataclass
class InvestigationError:
    """
    Structured error record for investigation failures.

    Attributes:
        error_type: Severity class — "fatal" | "recoverable" | "expected"
        component: Originating subsystem — "bedrock" | "mcp" | "config" | "events"
        message: Human-readable error description
        iteration: Loop iteration number when error occurred
        timestamp: ISO-8601 UTC timestamp
    """

    error_type: str
    component: str
    message: str
    iteration: int
    timestamp: str

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "event": "error",
            "error_type": self.error_type,
            "component": self.component,
            "message": self.message,
            "iteration": self.iteration,
            "timestamp": self.timestamp,
        }


class InvestigationAgent:
    """
    Orchestrates the autonomous investigation lifecycle.

    The agent sends alert context to Bedrock, routes tool calls through the MCP
    client, maintains conversation history, and terminates when either the LLM
    signals completion or the iteration budget is exhausted.

    Args:
        bedrock_client: Configured BedrockClient instance
        mcp_client: Connected (or connectable) MCPClient instance
        max_iterations: Hard cap on Bedrock converse turns (default: 10)
        observability: Optional DDTraceWrapper for APM instrumentation
    """

    def __init__(
        self,
        bedrock_client: BedrockClient,
        mcp_client: MCPClient,
        max_iterations: int = 10,
        observability: Optional["DDTraceWrapper"] = None,
    ) -> None:
        self.bedrock_client = bedrock_client
        self.mcp_client = mcp_client
        self.max_iterations = max_iterations
        self.observability = observability
        self._blast_radius: Optional[BlastRadiusReport] = None

    def investigate(self, scenario: AlertScenario) -> RCAReport:
        """
        Run the investigation and return an RCA report.

        Executes the async investigation loop synchronously so callers do not
        need to manage an event loop directly.

        Args:
            scenario: Alert scenario to investigate

        Returns:
            RCAReport with findings and metadata
        """
        return asyncio.run(self._investigate_async(scenario))

    async def _investigate_async(self, scenario: AlertScenario) -> RCAReport:
        scenario_id = scenario.name

        logger.info(
            json.dumps(
                {
                    "event": "investigation.start",
                    "scenario": scenario_id,
                    "max_iterations": self.max_iterations,
                }
            )
        )

        # Create workflow span if LLM Observability is enabled
        workflow_span = None
        if LLMOBS_AVAILABLE and self.observability and hasattr(self.observability, 'llmobs_enabled') and self.observability.llmobs_enabled:
            try:
                workflow_span = LLMObs.workflow(
                    name="incident_investigation",
                    session_id=scenario_id,
                    metadata={
                        "alert_name": scenario.name,
                        "description": scenario.description,
                        "max_iterations": self.max_iterations,
                    }
                ).__enter__()
            except Exception as e:
                logger.warning(f"Failed to create workflow span: {e}")

        try:
            self._blast_radius = BlastRadiusCalculator.compute_preliminary(scenario)
            print(format_blast_radius_card(self._blast_radius))

            # Build initial user message from alert context
            if isinstance(scenario.initial_context, dict):
                context_str = json.dumps(scenario.initial_context, indent=2)
            else:
                context_str = str(scenario.initial_context)

            blast_context = format_blast_radius_context(self._blast_radius)

            initial_prompt = (
                f"Investigate the following alert: {scenario.name}\n\n"
                f"Description: {scenario.description}\n\n"
                f"Initial Context:\n{context_str}\n\n"
                f"{blast_context}"
            )

            messages: list[dict[str, Any]] = [
                self.bedrock_client.format_message("user", initial_prompt)
            ]

            iteration = 0

            while iteration < self.max_iterations:
                logger.info(
                    json.dumps(
                        {
                            "event": "iteration.start",
                            "iteration": iteration + 1,
                            "scenario": scenario_id,
                            "message_count": len(messages),
                        }
                    )
                )

                # --- Bedrock turn ---
                try:
                    bedrock_response = self._conversation_turn(
                        messages, scenario_id, iteration
                    )
                except (BedrockAuthError, BedrockResponseError) as exc:
                    err = InvestigationError(
                        error_type="fatal",
                        component="bedrock",
                        message=str(exc),
                        iteration=iteration + 1,
                        timestamp=_utc_now(),
                    )
                    logger.error(json.dumps(err.to_log_dict()))
                    return self._generate_rca(
                        messages, iteration, scenario.name, terminated_early=True
                    )

                messages.append(bedrock_response.message)
                iteration += 1

                logger.info(
                    json.dumps(
                        {
                            "event": "iteration.end",
                            "iteration": iteration,
                            "scenario": scenario_id,
                            "stop_reason": bedrock_response.stop_reason,
                            "tool_uses": len(bedrock_response.tool_uses),
                        }
                    )
                )

                # Natural completion: no tool uses requested
                if not bedrock_response.tool_uses:
                    logger.info(
                        json.dumps(
                            {
                                "event": "investigation.complete",
                                "scenario": scenario_id,
                                "iterations": iteration,
                                "reason": "natural_completion",
                            }
                        )
                    )
                    break

                # --- Tool execution ---
                try:
                    tool_result_message = await self._execute_tools(
                        bedrock_response.tool_uses, scenario_id, iteration
                    )
                except MCPConnectionError as exc:
                    err = InvestigationError(
                        error_type="fatal",
                        component="mcp",
                        message=str(exc),
                        iteration=iteration,
                        timestamp=_utc_now(),
                    )
                    logger.error(json.dumps(err.to_log_dict()))
                    return self._generate_rca(
                        messages, iteration, scenario.name, terminated_early=True
                    )

                if tool_result_message:
                    messages.append(tool_result_message)

            if iteration >= self.max_iterations:
                logger.info(
                    json.dumps(
                        {
                            "event": "investigation.complete",
                            "scenario": scenario_id,
                            "iterations": iteration,
                            "reason": "max_iterations_reached",
                        }
                    )
                )

            return self._generate_rca(messages, iteration, scenario.name)
        
        finally:
            # Close workflow span
            if workflow_span is not None:
                try:
                    workflow_span.__exit__(None, None, None)
                except Exception as e:
                    logger.warning(f"Failed to close workflow span: {e}")

    def _conversation_turn(
        self,
        messages: list[dict[str, Any]],
        scenario_id: str,
        iteration: int,
    ) -> BedrockResponse:
        """Send messages to Bedrock with tool schemas and system prompt, optionally traced."""
        if self.observability is not None:
            return self.observability.trace_bedrock_call(
                scenario_id=scenario_id,
                fn=self.bedrock_client.converse,
                messages=messages,
                iteration=iteration,
                tool_config=GIT_TOOL_CONFIG,
                system=SYSTEM_PROMPT,
            )
        return self.bedrock_client.converse(
            messages=messages,
            tool_config=GIT_TOOL_CONFIG,
            system=SYSTEM_PROMPT,
        )

    async def _execute_tools(
        self,
        tool_uses: list[ToolUse],
        scenario_id: str,
        iteration: int,
    ) -> Optional[dict[str, Any]]:
        """
        Execute all tool calls concurrently and return a combined toolResult message.

        Tool-level failures are treated as recoverable — the error is logged and an
        error toolResult is appended so Bedrock can continue reasoning.

        ENHANCED: Tracks tool execution with LLM Observability SDK.

        Raises:
            MCPConnectionError: Re-raised when the MCP client is not connected
                               (fatal — caller should terminate the investigation).
        """
        tool_result_content: list[dict[str, Any]] = []

        for tool_use in tool_uses:
            logger.info(
                json.dumps(
                    {
                        "event": "tool.call",
                        "tool": tool_use.name,
                        "tool_use_id": tool_use.tool_use_id,
                        "iteration": iteration,
                        "scenario": scenario_id,
                    }
                )
            )

            # Create tool span if LLM Observability is enabled
            tool_span = None
            if LLMOBS_AVAILABLE and self.observability and hasattr(self.observability, 'llmobs_enabled') and self.observability.llmobs_enabled:
                try:
                    tool_span = LLMObs.tool(
                        name=tool_use.name,
                        input=tool_use.input,
                        metadata={
                            "tool_use_id": tool_use.tool_use_id,
                            "iteration": iteration,
                            "scenario": scenario_id,
                        }
                    ).__enter__()
                except Exception as e:
                    logger.warning(f"Failed to create tool span: {e}")

            # Route git tools locally; forward everything else to MCP
            try:
                if tool_use.name in GIT_TOOL_NAMES:
                    raw = await asyncio.to_thread(
                        execute_git_tool, tool_use.name, tool_use.input
                    )
                    # Wrap as an MCPToolResponse-compatible namedtuple-like object
                    from types import SimpleNamespace
                    response = SimpleNamespace(
                        success=raw.get("success", False),
                        result=raw.get("result"),
                        error=raw.get("error"),
                    )
                else:
                    response = await self.mcp_client.call_tool(
                        tool_use.name, tool_use.input
                    )
            except MCPConnectionError:
                if tool_span:
                    try:
                        tool_span.__exit__(MCPConnectionError, None, None)
                    except:
                        pass
                raise
            except Exception as exc:
                component = "git" if tool_use.name in GIT_TOOL_NAMES else "mcp"
                _log_recoverable_error(component, str(exc), iteration)
                tool_result_content.append(
                    _error_tool_result(tool_use.tool_use_id, str(exc))
                )
                if tool_span:
                    try:
                        tool_span.error = str(exc)
                        tool_span.error_type = type(exc).__name__
                        tool_span.__exit__(type(exc), exc, None)
                    except:
                        pass
                continue

            if response.success:
                content_payload = _serialize_tool_result(response.result)
                tool_result_content.append(
                    {
                        "toolResult": {
                            "toolUseId": tool_use.tool_use_id,
                            "content": [content_payload],
                        }
                    }
                )
                logger.debug(
                    json.dumps(
                        {
                            "event": "tool.success",
                            "tool": tool_use.name,
                            "iteration": iteration,
                        }
                    )
                )
                
                # Set tool span output
                if tool_span:
                    try:
                        tool_span.output = response.result
                        tool_span.__exit__(None, None, None)
                    except Exception as e:
                        logger.warning(f"Failed to close tool span: {e}")
            else:
                _log_recoverable_error("mcp", response.error or "unknown error", iteration)
                tool_result_content.append(
                    _error_tool_result(
                        tool_use.tool_use_id, response.error or "unknown error"
                    )
                )
                
                # Mark tool span as error
                if tool_span:
                    try:
                        tool_span.error = response.error or "unknown error"
                        tool_span.__exit__(None, None, None)
                    except:
                        pass

        if not tool_result_content:
            return None

        return {"role": "user", "content": tool_result_content}

    def _generate_rca(
        self,
        messages: list[dict[str, Any]],
        iteration: int,
        alert_name: str,
        terminated_early: bool = False,
    ) -> RCAReport:
        """
        Build an RCA report from the accumulated conversation history.

        Extracts text blocks from assistant messages as key findings and uses
        the last assistant text block as the investigation summary.
        
        ENHANCED: Includes quality evaluation of the RCA report.
        """
        logger.info(
            json.dumps(
                {
                    "event": "rca.generate",
                    "iterations_used": iteration,
                    "alert_name": alert_name,
                }
            )
        )

        key_findings: list[str] = []
        investigation_summary = ""

        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            for block in msg.get("content", []):
                text = block.get("text", "").strip()
                if len(text) > 10:
                    key_findings.append(text)
                    investigation_summary = text

        # Cap findings
        key_findings = key_findings[:10]

        if not investigation_summary:
            investigation_summary = (
                "Investigation terminated early due to an error."
                if terminated_early
                else "Investigation completed without conclusive findings."
            )

        report = RCAReport(
            alert_name=alert_name,
            investigation_summary=investigation_summary,
            key_findings=key_findings,
            iterations_used=iteration,
            timestamp=_utc_now(),
        )

        if self._blast_radius is not None:
            report.blast_radius = BlastRadiusCalculator.merge_final(
                self._blast_radius, messages, investigation_summary
            )
            print(format_blast_radius_card(report.blast_radius))

        # Evaluate RCA quality
        quality_metrics = self._evaluate_rca_quality(report, messages, terminated_early)
        
        logger.info(
            json.dumps(
                {
                    "event": "rca.complete",
                    "alert_name": alert_name,
                    "iterations_used": iteration,
                    "findings_count": len(key_findings),
                    "quality_score": quality_metrics["overall_score"],
                    "quality_rating": quality_metrics["rating"],
                }
            )
        )
        
        # Submit evaluation to LLM Observability if available
        if LLMOBS_AVAILABLE and self.observability and hasattr(self.observability, 'llmobs_enabled') and self.observability.llmobs_enabled:
            try:
                # Submit quality metrics as evaluations
                LLMObs.submit_evaluation(
                    span_id=None,  # Will attach to current span
                    label="rca_quality",
                    metric_type="score",
                    value=quality_metrics["overall_score"],
                )
                
                LLMObs.submit_evaluation(
                    span_id=None,
                    label="completeness",
                    metric_type="categorical",
                    value="pass" if quality_metrics["completeness_check"] else "fail",
                )
                
                LLMObs.submit_evaluation(
                    span_id=None,
                    label="iteration_efficiency",
                    metric_type="score",
                    value=quality_metrics["iteration_efficiency"],
                )
            except Exception as e:
                logger.warning(f"Failed to submit quality evaluations: {e}")

        return report
    
    def _evaluate_rca_quality(
        self,
        report: RCAReport,
        messages: list[dict[str, Any]],
        terminated_early: bool
    ) -> dict[str, Any]:
        """
        Evaluate the quality of an RCA report using multiple metrics.
        
        Returns a dictionary with quality scores and ratings.
        """
        metrics = {}
        
        # 1. Completeness Check (0-1)
        # RCA should have at least 3 findings and a summary > 50 chars
        has_min_findings = len(report.key_findings) >= 3
        has_substantial_summary = len(report.investigation_summary) > 50
        metrics["completeness_check"] = has_min_findings and has_substantial_summary
        metrics["completeness_score"] = (
            (1.0 if has_min_findings else 0.5) +
            (1.0 if has_substantial_summary else 0.5)
        ) / 2.0
        
        # 2. Iteration Efficiency (0-1)
        # Good investigations should complete in 5-7 iterations (not too fast, not max)
        efficiency = 1.0 - (report.iterations_used / self.max_iterations)
        if 5 <= report.iterations_used <= 7:
            efficiency = 1.0  # Ideal range
        elif report.iterations_used < 3:
            efficiency = 0.6  # Too fast - might have missed context
        metrics["iteration_efficiency"] = round(efficiency, 2)
        
        # 3. Tool Usage Score (0-1)
        # Count how many tool calls were made
        tool_call_count = 0
        for msg in messages:
            if msg.get("role") == "user":
                for block in msg.get("content", []):
                    if isinstance(block, dict) and "toolResult" in block:
                        tool_call_count += 1
        
        # Good investigations use 3-8 tools
        if 3 <= tool_call_count <= 8:
            tool_usage_score = 1.0
        elif tool_call_count < 3:
            tool_usage_score = 0.6  # Underutilized tools
        else:
            tool_usage_score = 0.8  # Over-reliance on tools
        
        metrics["tool_usage_score"] = tool_usage_score
        metrics["tool_calls"] = tool_call_count
        
        # 4. Findings Quality (0-1)
        # Assess based on finding count and diversity
        findings_count = len(report.key_findings)
        if findings_count >= 5:
            findings_quality = 1.0  # Excellent
        elif findings_count >= 3:
            findings_quality = 0.8  # Good
        elif findings_count >= 1:
            findings_quality = 0.6  # Acceptable
        else:
            findings_quality = 0.3  # Poor
        
        metrics["findings_quality"] = findings_quality
        metrics["findings_count"] = findings_count
        
        # 5. Early Termination Penalty
        termination_penalty = 0.3 if terminated_early else 0.0
        
        # Calculate Overall Score (0-1)
        overall_score = (
            metrics["completeness_score"] * 0.30 +  # 30% weight
            metrics["iteration_efficiency"] * 0.25 +  # 25% weight
            metrics["tool_usage_score"] * 0.20 +      # 20% weight
            metrics["findings_quality"] * 0.25        # 25% weight
        ) - termination_penalty
        
        metrics["overall_score"] = round(max(0.0, min(1.0, overall_score)), 2)
        
        # Determine Rating
        if metrics["overall_score"] >= 0.85:
            rating = "excellent"
        elif metrics["overall_score"] >= 0.70:
            rating = "good"
        elif metrics["overall_score"] >= 0.55:
            rating = "acceptable"
        else:
            rating = "needs_improvement"
        
        metrics["rating"] = rating
        metrics["terminated_early"] = terminated_early
        
        return metrics


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize_tool_result(result: Any) -> dict[str, Any]:
    """Convert an MCP tool result to a Bedrock content block."""
    if result is None:
        return {"text": ""}
    if hasattr(result, "content"):
        content = result.content
        if isinstance(content, list):
            parts = []
            for item in content:
                if hasattr(item, "text"):
                    parts.append(item.text)
                else:
                    parts.append(str(item))
            return {"text": "\n".join(parts)}
        return {"text": str(content)}
    if isinstance(result, dict):
        return {"json": result}
    return {"text": str(result)}


def _error_tool_result(tool_use_id: str, error_msg: str) -> dict[str, Any]:
    return {
        "toolResult": {
            "toolUseId": tool_use_id,
            "content": [{"text": f"Tool error: {error_msg}"}],
            "status": "error",
        }
    }


def _log_recoverable_error(component: str, message: str, iteration: int) -> None:
    err = InvestigationError(
        error_type="recoverable",
        component=component,
        message=message,
        iteration=iteration,
        timestamp=_utc_now(),
    )
    logger.warning(json.dumps(err.to_log_dict()))
