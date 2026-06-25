"""Datadog LLM Observability integration for ``track_aiops``.

This module initializes Datadog LLM Observability in agentless mode and
provides a traced wrapper around Bedrock invocations. The :func:`traced_llm`
function is decorated with ``@llm`` so each call emits an LLM span, which is
annotated with the prompt, the response text, and token usage metrics.

By design this module has **zero** CLI/IO knowledge — it neither parses
arguments nor writes to stdout/stderr. It is reusable by future workflow or
agent modules. Transport lives in ``track_aiops.bedrock_client``; this module
wraps those calls from the outside, keeping tracing and transport decoupled.

Requirements: 4.1, 4.2, 4.3, 4.5, 5.2
"""

from ddtrace.llmobs import LLMObs
from ddtrace.llmobs.decorators import llm

from .bedrock_client import BedrockClient, BedrockResponse
from .config import Settings

# Module-level guard so repeated ``enable_llmobs`` calls are no-ops. This keeps
# enabling idempotent: calling it multiple times does not re-enable LLMObs or
# create duplicate spans (Property 5: Idempotent Enable).
_enabled = False


def enable_llmobs(settings: Settings) -> None:
    """Enable Datadog LLM Observability in agentless mode.

    Idempotent: the first call enables LLMObs with the configured ml_app, API
    key, and site; subsequent calls are no-ops and never raise.

    Args:
        settings: Validated configuration supplying the ml_app name, Datadog
            API key, and site.
    """
    global _enabled
    if _enabled:
        return

    LLMObs.enable(
        ml_app=settings.dd_llmobs_ml_app,
        agentless_enabled=True,
        api_key=settings.dd_api_key,
        site=settings.dd_site,
    )
    _enabled = True


@llm(model_name="nova-pro", model_provider="bedrock")
def traced_llm(client: BedrockClient, prompt: str) -> BedrockResponse:
    """Invoke Bedrock and annotate the LLM span with input/output/metrics.

    The ``@llm`` decorator creates a span with model_name ``nova-pro`` and
    model_provider ``bedrock``. After invoking the model, the span is annotated
    with the prompt (input), the response text (output), and token usage.

    Args:
        client: The Bedrock transport client to invoke.
        prompt: The user prompt to send to the model.

    Returns:
        The :class:`BedrockResponse` returned by ``client.invoke``.
    """
    response = client.invoke(prompt)

    LLMObs.annotate(
        input_data=prompt,
        output_data=response.text,
        metrics={
            "input_tokens": response.usage["inputTokens"],
            "output_tokens": response.usage["outputTokens"],
            "total_tokens": response.usage["totalTokens"],
        },
    )

    return response


def flush() -> None:
    """Flush all pending spans to Datadog.

    Should be called before process exit (typically in a ``finally`` block) to
    ensure spans are submitted regardless of success or failure.
    """
    LLMObs.flush()
