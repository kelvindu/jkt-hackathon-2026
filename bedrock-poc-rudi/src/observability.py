"""
LLM Observability module — DDTrace wrapper for Bedrock API calls.

Instruments all converse() calls with Datadog APM spans, capturing:
- Alert scenario context
- Token usage metrics (input / output / total)
- Stop reason
- Error status on exceptions

ENHANCED: Uses Datadog LLM Observability SDK for full agent monitoring.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""

import logging
from typing import Any, Callable, Optional

from ddtrace import tracer

# LLM Observability SDK for enhanced agent monitoring
try:
    from ddtrace.llmobs import LLMObs
    from ddtrace.llmobs._integrations import BedrockIntegration
    
    LLMOBS_AVAILABLE = True
except ImportError:
    LLMOBS_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("ddtrace.llmobs not available - falling back to basic APM tracing")

logger = logging.getLogger(__name__)

_SERVICE_NAME = "incident-response-agent"
_MODEL_ID = "amazon.nova-micro-v1:0"


class DDTraceWrapper:
    """
    Wraps Bedrock converse() calls with Datadog APM tracing.

    Each call produces a ``bedrock.converse`` span tagged with the alert scenario
    ID, model name, iteration number, and token usage metrics.  Exceptions are
    marked as errors on the span before being re-raised.

    Args:
        service_name: Datadog service name for all produced spans
    """

    def __init__(self, service_name: str = _SERVICE_NAME, enable_llmobs: bool = True) -> None:
        self.service_name = service_name
        self.llmobs_enabled = enable_llmobs and LLMOBS_AVAILABLE
        
        # Initialize LLM Observability SDK if available
        if self.llmobs_enabled:
            try:
                LLMObs.enable(
                    ml_app=service_name,
                    integrations_enabled=True,
                    agentless_enabled=True,
                )
                logger.info("LLM Observability SDK enabled")
            except Exception as e:
                logger.warning(f"Failed to enable LLM Observability SDK: {e}")
                self.llmobs_enabled = False

    def trace_bedrock_call(
        self,
        scenario_id: str,
        fn: Callable[..., Any],
        *args: Any,
        iteration: int = 0,
        **kwargs: Any,
    ) -> Any:
        """
        Execute ``fn`` inside a ``bedrock.converse`` APM span.

        If LLM Observability SDK is enabled, creates an LLM span with full
        input/output capture. Otherwise falls back to basic APM tracing.

        Args:
            scenario_id: Alert scenario identifier used as a trace tag
            fn: Callable to invoke (typically ``BedrockClient.converse``)
            *args: Positional arguments forwarded to ``fn``
            iteration: Current loop iteration — tagged on the span
            **kwargs: Keyword arguments forwarded to ``fn``

        Returns:
            Return value of ``fn``

        Raises:
            Any exception raised by ``fn`` — span is marked as error first
        """
        if self.llmobs_enabled:
            return self._trace_with_llmobs(scenario_id, fn, iteration, *args, **kwargs)
        else:
            return self._trace_with_apm(scenario_id, fn, iteration, *args, **kwargs)
    
    def _trace_with_llmobs(
        self,
        scenario_id: str,
        fn: Callable[..., Any],
        iteration: int,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Trace using LLM Observability SDK for enhanced visibility."""
        messages = kwargs.get("messages", [])
        
        # Extract input messages for LLM span
        input_messages = []
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role", "user")
                content = msg.get("content", [])
                
                # Format content blocks as text
                text_parts = []
                for block in content if isinstance(content, list) else [content]:
                    if isinstance(block, dict):
                        if "text" in block:
                            text_parts.append(block["text"])
                        elif "toolResult" in block:
                            text_parts.append(f"[Tool Result: {block['toolResult'].get('toolUseId', 'unknown')}]")
                    else:
                        text_parts.append(str(block))
                
                input_messages.append({
                    "role": role,
                    "content": " ".join(text_parts) if text_parts else ""
                })
        
        span = LLMObs.llm(
            model_name=_MODEL_ID,
            model_provider="bedrock",
            input_messages=input_messages,
            metadata={
                "scenario": scenario_id,
                "iteration": iteration,
                "service": self.service_name,
            },
        )
        
        try:
            result = fn(*args, **kwargs)
            
            # Extract output messages
            output_messages = []
            if hasattr(result, "message") and isinstance(result.message, dict):
                content = result.message.get("content", [])
                text_parts = []
                
                for block in content if isinstance(content, list) else [content]:
                    if isinstance(block, dict):
                        if "text" in block:
                            text_parts.append(block["text"])
                        elif "toolUse" in block:
                            tool_use = block["toolUse"]
                            text_parts.append(
                                f"[Tool Call: {tool_use.get('name', 'unknown')}]"
                            )
                
                output_messages.append({
                    "role": "assistant",
                    "content": " ".join(text_parts) if text_parts else ""
                })
            
            span.output_messages = output_messages
            
            # Capture token metrics
            if hasattr(result, "usage") and isinstance(result.usage, dict):
                span.metrics = {
                    "input_tokens": result.usage.get("inputTokens", 0),
                    "output_tokens": result.usage.get("outputTokens", 0),
                    "total_tokens": result.usage.get("totalTokens", 0),
                }
            
            # Tag stop reason
            if hasattr(result, "stop_reason"):
                span.metadata["stop_reason"] = result.stop_reason
            
            return result
            
        except Exception as exc:
            span.error = str(exc)
            span.error_type = type(exc).__name__
            raise
    
    def _trace_with_apm(
        self,
        scenario_id: str,
        fn: Callable[..., Any],
        iteration: int,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Fallback to basic APM tracing when LLM Observability SDK is unavailable."""
        with tracer.trace(
            "bedrock.converse",
            service=self.service_name,
            resource=_MODEL_ID,
        ) as span:
            span.set_tag("alert.scenario", scenario_id)
            span.set_tag("model", _MODEL_ID)
            span.set_tag("operation", "bedrock.converse")
            span.set_tag("iteration", iteration)

            try:
                result = fn(*args, **kwargs)

                # Capture token usage from BedrockResponse
                if hasattr(result, "usage") and isinstance(result.usage, dict):
                    span.set_metric(
                        "bedrock.input_tokens", result.usage.get("inputTokens", 0)
                    )
                    span.set_metric(
                        "bedrock.output_tokens", result.usage.get("outputTokens", 0)
                    )
                    span.set_metric(
                        "bedrock.total_tokens", result.usage.get("totalTokens", 0)
                    )

                if hasattr(result, "stop_reason"):
                    span.set_tag("bedrock.stop_reason", result.stop_reason)

                return result

            except Exception as exc:
                span.set_tag("error", True)
                span.set_tag("error.type", type(exc).__name__)
                span.set_tag("error.message", str(exc))
                raise
