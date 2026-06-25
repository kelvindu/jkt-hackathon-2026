"""CLI entrypoint for ``track_aiops``.

Parses ``ask "<prompt>"`` from the command line, orchestrates the call chain
(load config → enable observability → invoke the traced LLM call → print the
response and token usage), and guarantees that pending Datadog spans are
flushed before the process exits.

Usage:
    python -m track_aiops.cli ask "<prompt>"

This module owns argument parsing and stdout/stderr only. Configuration lives
in ``track_aiops.config``, transport in ``track_aiops.bedrock_client``, and
tracing in ``track_aiops.observability``.

Requirements: 1.1, 1.2, 1.3, 1.4, 4.4, 5.3
"""

import sys

from . import config
from .bedrock_client import BedrockClient
from .observability import enable_llmobs, flush, traced_llm

USAGE = 'usage: python -m track_aiops.cli ask "<prompt>"'


def _parse_args(argv: list[str]) -> str | None:
    """Extract the prompt from ``argv`` (excluding the program name).

    Args:
        argv: Argument list in the form ``["ask", "<prompt>"]``.

    Returns:
        The prompt string when ``argv`` is a valid ``ask "<prompt>"`` invocation
        with a non-empty prompt, otherwise ``None``.
    """
    if len(argv) != 2:
        return None
    command, prompt = argv
    if command != "ask" or not prompt.strip():
        return None
    return prompt


def main(argv: list[str] | None = None) -> int:
    """Run the CLI: parse args, invoke Bedrock, print output, flush spans.

    Args:
        argv: Optional argument list (excluding the program name). Defaults to
            ``sys.argv[1:]`` when not provided, so tests can pass args directly.

    Returns:
        ``0`` on success; a non-zero exit code when no/invalid prompt is given
        or when the invocation fails.
    """
    args = sys.argv[1:] if argv is None else argv

    prompt = _parse_args(args)
    if prompt is None:
        print(USAGE, file=sys.stderr)
        return 2

    try:
        settings = config.load()
        enable_llmobs(settings)
        client = BedrockClient(region=settings.aws_region, model_id=settings.model_id)
        response = traced_llm(client, prompt)
        print(response.text)
        print(f"[tokens: {response.usage}] [stop: {response.stop_reason}]")
        return 0
    except Exception as exc:  # noqa: BLE001 - surface any failure to the user
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        flush()


if __name__ == "__main__":
    sys.exit(main())
