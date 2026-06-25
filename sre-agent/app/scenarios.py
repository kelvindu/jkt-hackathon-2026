"""Alert scenario model + loader (JSON).

A scenario describes the alert the agent investigates. Scenarios can come from a
bundled JSON file (CLI demo) or be synthesized from a live Datadog webhook
payload (webhook server) — see :func:`from_webhook`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AlertScenario:
    name: str
    description: str
    initial_context: Any
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def scenario_id(self) -> str:
        return self.name.lower().replace(" ", "-")[:80] or "unknown-alert"


_REQUIRED = {"name", "description", "initial_context"}


def load_scenarios(file_path: str) -> list[AlertScenario]:
    """Load one or more scenarios from a JSON file (top-level ``scenarios`` array)."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Scenario file not found: {file_path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("scenarios", []) if isinstance(data, dict) else []
    if not raw:
        raise ValueError(f"No 'scenarios' array in {file_path}")
    out: list[AlertScenario] = []
    for idx, s in enumerate(raw):
        missing = _REQUIRED - set(s)
        if missing:
            raise ValueError(f"scenario[{idx}] missing fields: {', '.join(sorted(missing))}")
        out.append(
            AlertScenario(
                name=s["name"],
                description=s["description"],
                initial_context=s["initial_context"],
                metadata=s.get("metadata", {}),
            )
        )
    return out


def from_webhook(sanitized_payload: dict[str, Any]) -> AlertScenario:
    """Build a scenario from a sanitized Datadog monitor webhook payload."""
    title = str(sanitized_payload.get("title", "Datadog Alert")).strip() or "Datadog Alert"
    body = str(sanitized_payload.get("body", ""))
    tags = str(sanitized_payload.get("tags", ""))
    service = _tag_value(tags, "service") or "auth-service"

    return AlertScenario(
        name=title,
        description=body[:500] or title,
        initial_context={
            "service": service,
            "endpoint": "/api/v1/auth/validate",
            "alert_body": body,
            "tags": tags,
            "monitor_url": sanitized_payload.get("url", ""),
            "suspected_technical_cause": (
                "HTTP 5xx spike / latency on auth-service — likely injected DB "
                "connection-pool timeout fault in AuthValidationService"
            ),
            "suspected_file": "src/main/java/com/hackathon/auth/service/AuthValidationService.java",
            "error_codes": ["500", "503"],
            "symptoms": ["DatabaseTimeoutException", "connection pool exhaustion", "elevated latency"],
            "business_metrics": {"stuck_customers": 42, "financial_bleed_rate_usd_per_min": 145},
        },
        metadata={
            "severity": "high",
            "team": _tag_value(tags, "team") or "platform",
            "source": "datadog-webhook",
        },
    )


def _tag_value(tags: str, key: str) -> str:
    for pair in tags.split(","):
        if ":" in pair:
            k, _, v = pair.partition(":")
            if k.strip() == key:
                return v.strip()
    return ""
