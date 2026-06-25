"""Datadog LLM Observability integration.

Enables LLMObs in agentless mode and provides a traced Bedrock wrapper plus the
``@workflow / @task / @tool / @llm`` decorators re-exported for the agent.

Earns checklist points:
- DD #1 First Trace  — LLMObs.enable(agentless) + LLMObs.flush()
- DD #3 Tool Visible — tool spans nested in the workflow span
- DD #4 Cost Tracked — token metrics + USD cost annotated on every LLM span
- DD #6 End-to-End   — all four span types in one trace
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from .bedrock_client import BedrockResponse
from .config import Settings, estimate_cost_usd

logger = logging.getLogger(__name__)

# LLMObs SDK is optional at import time so unit tests run without ddtrace.
try:
    from ddtrace.llmobs import LLMObs
    from ddtrace.llmobs.decorators import llm, task, tool, workflow

    LLMOBS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only in minimal envs
    LLMOBS_AVAILABLE = False

    def _noop_decorator(*_dargs: Any, **_dkwargs: Any) -> Callable:
        def wrap(fn: Callable) -> Callable:
            return fn

        # Support both @workflow and @workflow(name=...) usage.
        if len(_dargs) == 1 and callable(_dargs[0]) and not _dkwargs:
            return _dargs[0]
        return wrap

    workflow = task = tool = llm = _noop_decorator  # type: ignore[assignment]
    LLMObs = None  # type: ignore[assignment]


_enabled = False


def enable(settings: Settings) -> bool:
    """Enable LLM Observability in agentless mode. Idempotent; never raises.

    Returns:
        True if LLMObs is active after the call, else False.
    """
    global _enabled
    if _enabled:
        return True
    if not LLMOBS_AVAILABLE:
        logger.warning("ddtrace.llmobs unavailable — running without LLM Observability")
        return False
    if not settings.has_datadog:
        logger.warning("DD_API_KEY not set — LLM Observability disabled")
        return False
    try:
        LLMObs.enable(
            ml_app=settings.dd_llmobs_ml_app,
            agentless_enabled=True,
            api_key=settings.dd_api_key,
            site=settings.dd_site,
        )
        _enabled = True
        logger.info("LLM Observability enabled (agentless, ml_app=%s)", settings.dd_llmobs_ml_app)
        return True
    except Exception as exc:  # noqa: BLE001 - never let observability crash the agent
        logger.warning("Failed to enable LLM Observability: %s", exc)
        return False


def is_enabled() -> bool:
    return _enabled


def flush() -> None:
    """Flush pending spans to Datadog. Call before process/turn exit."""
    if _enabled and LLMOBS_AVAILABLE:
        try:
            LLMObs.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLMObs.flush failed: %s", exc)


def annotate(**kwargs: Any) -> None:
    """Annotate the current span; safe no-op when LLMObs is unavailable."""
    if _enabled and LLMOBS_AVAILABLE:
        try:
            LLMObs.annotate(**kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.debug("LLMObs.annotate failed: %s", exc)


def trace_bedrock_call(
    settings: Settings,
    converse_fn: Callable[..., BedrockResponse],
    *,
    iteration: int,
    scenario: str,
    **converse_kwargs: Any,
) -> BedrockResponse:
    """Invoke ``converse_fn`` inside an ``@llm`` span with cost + token metrics.

    The span captures input/output messages, ``inputTokens`` / ``outputTokens`` /
    ``total_tokens``, the estimated USD ``cost``, and the stop reason. On error
    the span is marked failed and the exception re-raised (DD #5 error handling).
    """
    if not (_enabled and LLMOBS_AVAILABLE):
        return converse_fn(**converse_kwargs)

    messages = converse_kwargs.get("messages", [])
    span_ctx = LLMObs.llm(
        model_name=settings.model_name,
        model_provider=settings.model_provider,
        name=f"bedrock.converse.iter_{iteration}",
    )
    with span_ctx:
        LLMObs.annotate(
            input_data=_flatten_messages(messages),
            metadata={"scenario": scenario, "iteration": iteration, "model_id": settings.model_id},
        )
        try:
            result = converse_fn(**converse_kwargs)
        except Exception as exc:  # noqa: BLE001
            annotate(tags={"error": "true", "error.type": type(exc).__name__})
            raise

        usage = result.usage or {}
        input_tokens = int(usage.get("inputTokens", 0))
        output_tokens = int(usage.get("outputTokens", 0))
        total_tokens = int(usage.get("totalTokens", input_tokens + output_tokens))
        cost = estimate_cost_usd(input_tokens, output_tokens)

        LLMObs.annotate(
            output_data=result.text or f"[stop:{result.stop_reason}]",
            metrics={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            },
            metadata={
                "stop_reason": result.stop_reason,
                "tool_uses": len(result.tool_uses),
                # Cost as metadata + tag so it shows in both trace view and metrics.
                "cost_usd": cost,
            },
            tags={"stop_reason": result.stop_reason, "cost_usd": str(cost)},
        )
        return result


def _flatten_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Reduce Bedrock content-block messages to {role, content:str} for spans."""
    flat: list[dict[str, str]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "user")
        parts: list[str] = []
        for block in msg.get("content", []) or []:
            if not isinstance(block, dict):
                parts.append(str(block))
            elif "text" in block:
                parts.append(block["text"])
            elif "toolUse" in block:
                parts.append(f"[tool_call: {block['toolUse'].get('name', '?')}]")
            elif "toolResult" in block:
                parts.append(f"[tool_result: {block['toolResult'].get('toolUseId', '?')}]")
        flat.append({"role": role, "content": " ".join(parts)})
    return flat


__all__ = [
    "enable",
    "is_enabled",
    "flush",
    "annotate",
    "trace_bedrock_call",
    "workflow",
    "task",
    "tool",
    "llm",
    "LLMObs",
    "LLMOBS_AVAILABLE",
]
