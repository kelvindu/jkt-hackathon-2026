"""track_aiops: CLI to invoke AWS Bedrock Nova Pro and emit a Datadog LLM observability span.

This package wires together four concerns with clean module boundaries:

- ``config``        — load and validate environment settings (fail-fast)
- ``bedrock_client`` — pure boto3 transport to AWS Bedrock (no Datadog imports)
- ``observability`` — Datadog LLM Observability enable/annotate/flush (no CLI/IO imports)
- ``cli``           — entrypoint orchestration: parse → invoke → print → flush

Entry point: ``python -m track_aiops.cli ask "<prompt>"``
"""

__version__ = "0.1.0"
