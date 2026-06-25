"""Autonomous SRE Incident-Response Agent (EKS deployable).

A revamp of ``bedrock-poc-rudi`` aligned with the Jakarta Hackathon 2026
scoring checklist:

- AWS Bedrock ``amazon.nova-pro-v1:0`` via the Converse API (tool use)
- Datadog LLM Observability with ``@workflow / @task / @tool / @llm`` spans
- Token + USD cost tracking annotated on every LLM span
- Input guardrails (PII + prompt-injection redaction) on the webhook surface
- Graceful error handling that surfaces as spans instead of crashing
- Live operational tools against the running ``auth-service`` (incl. auto-remediation)

The package ships both a CLI demo (``app.main``) and a FastAPI webhook
server (``app.server``) that ``ops-simulator`` targets via ``WEBHOOK_URL``.
"""

__version__ = "1.0.0"
