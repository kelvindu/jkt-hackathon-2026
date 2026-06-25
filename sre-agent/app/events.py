"""Datadog Events v1 publisher for RCA reports.

Posts the RCA (and blast-radius card) as a Datadog Event so on-call engineers see
the agent's conclusion in the event stream. Retries on network/rate-limit errors
with exponential backoff; auth failures are non-retryable.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

import requests

from .blast_radius import format_blast_radius_card

if TYPE_CHECKING:
    from .agent import RCAReport

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0


class DatadogEventsPublisher:
    """Publishes RCA reports to ``https://api.{site}/api/v1/events``."""

    def __init__(self, api_key: str, site: str = "datadoghq.com") -> None:
        self.api_key = api_key
        self.site = site
        self._url = f"https://api.{site}/api/v1/events"

    def publish_rca(self, report: "RCAReport", scenario_id: str) -> bool:
        if not self.api_key:
            logger.warning(json.dumps({"event": "events.skipped", "reason": "no DD_API_KEY"}))
            return False

        payload = self._format(report, scenario_id)
        for attempt in range(_MAX_RETRIES):
            try:
                resp = requests.post(
                    self._url,
                    json=payload,
                    headers={"DD-API-KEY": self.api_key, "Content-Type": "application/json"},
                    timeout=30,
                )
                if resp.status_code == 202:
                    logger.info(json.dumps({"event": "events.published", "scenario_id": scenario_id}))
                    return True
                if resp.status_code == 403:
                    logger.error(json.dumps({"event": "events.auth_error", "status": 403}))
                    return False
                delay = _RETRY_BASE_DELAY * (2**attempt)
                logger.warning(
                    json.dumps({"event": "events.retry", "status": resp.status_code, "attempt": attempt + 1})
                )
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(delay)
            except requests.ConnectionError as exc:
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_BASE_DELAY * (2**attempt))
                else:
                    logger.error(json.dumps({"event": "events.network_error", "error": str(exc)}))
            except requests.RequestException as exc:
                logger.error(json.dumps({"event": "events.request_error", "error": str(exc)}))
                return False
        return False

    def _format(self, report: "RCAReport", scenario_id: str) -> dict[str, Any]:
        findings = (
            "\n".join(f"- {f}" for f in report.key_findings)
            if report.key_findings
            else "No specific findings recorded."
        )
        parts: list[str] = []
        if report.blast_radius is not None:
            parts.append(format_blast_radius_card(report.blast_radius).strip())
        parts.append(report.investigation_summary)
        parts.append(f"Key Findings:\n{findings}")
        return {
            "title": f"[SRE Agent] RCA: {report.alert_name}",
            "text": "\n\n".join(parts),
            "tags": [
                "agent:sre-incident-agent",
                f"scenario:{scenario_id}",
                f"iterations:{report.iterations_used}",
                f"remediated:{str(bool(report.remediated)).lower()}",
            ],
            "alert_type": "info" if report.remediated else "warning",
            "source_type_name": "sre-incident-agent",
        }
