"""
Datadog Events publisher module.

Publishes RCA reports as Datadog Events with retry logic and structured error
handling.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
"""

import json
import logging
import time
from typing import Any

import requests

from .agent import RCAReport
from .blast_radius import format_blast_radius_card

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds — doubles on each attempt (exponential backoff)


class DatadogEventsPublisher:
    """
    Publishes RCA reports to the Datadog Events v1 API.

    Retries up to ``_MAX_RETRIES`` times on network errors and rate-limit
    responses using exponential backoff.  Authentication failures are treated as
    non-retryable and return ``False`` immediately.

    Args:
        api_key: Datadog API key (DD-API-KEY header)
        site: Datadog site hostname, e.g. ``"datadoghq.com"`` or ``"datadoghq.eu"``
    """

    def __init__(self, api_key: str, site: str = "datadoghq.com") -> None:
        self.api_key = api_key
        self.site = site
        self._api_url = f"https://api.{site}/api/v1/events"

    def publish_rca(self, report: RCAReport, scenario_id: str) -> bool:
        """
        Publish an RCA report as a Datadog event.

        Args:
            report: RCAReport to publish
            scenario_id: Alert scenario identifier used as an event tag

        Returns:
            True if published successfully, False otherwise
        """
        payload = self._format_event(report, scenario_id)

        for attempt in range(_MAX_RETRIES):
            try:
                response = requests.post(
                    self._api_url,
                    json=payload,
                    headers={
                        "DD-API-KEY": self.api_key,
                        "Content-Type": "application/json",
                    },
                    timeout=30,
                )

                if response.status_code == 202:
                    logger.info(
                        json.dumps(
                            {
                                "event": "events.published",
                                "scenario_id": scenario_id,
                                "alert_name": report.alert_name,
                            }
                        )
                    )
                    return True

                if response.status_code == 403:
                    logger.error(
                        json.dumps(
                            {
                                "event": "events.auth_error",
                                "status_code": response.status_code,
                                "message": "Datadog API authentication failed — check DD_API_KEY",
                            }
                        )
                    )
                    return False

                if response.status_code == 429:
                    delay = _backoff_delay(attempt)
                    logger.warning(
                        json.dumps(
                            {
                                "event": "events.rate_limit",
                                "attempt": attempt + 1,
                                "retry_after_s": delay,
                            }
                        )
                    )
                    time.sleep(delay)
                    continue

                # Other non-success status — retry
                delay = _backoff_delay(attempt)
                logger.warning(
                    json.dumps(
                        {
                            "event": "events.unexpected_status",
                            "status_code": response.status_code,
                            "attempt": attempt + 1,
                            "retry_after_s": delay,
                        }
                    )
                )
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(delay)

            except requests.ConnectionError as exc:
                delay = _backoff_delay(attempt)
                logger.warning(
                    json.dumps(
                        {
                            "event": "events.network_error",
                            "error": str(exc),
                            "attempt": attempt + 1,
                            "retry_after_s": delay,
                        }
                    )
                )
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(delay)

            except requests.RequestException as exc:
                logger.error(
                    json.dumps(
                        {
                            "event": "events.request_error",
                            "error": str(exc),
                        }
                    )
                )
                return False

        logger.error(
            json.dumps(
                {
                    "event": "events.publish_failed",
                    "scenario_id": scenario_id,
                    "message": f"Failed to publish event after {_MAX_RETRIES} attempts",
                }
            )
        )
        return False

    def _format_event(self, report: RCAReport, scenario_id: str) -> dict[str, Any]:
        """
        Serialize an RCAReport into a Datadog Events API payload.

        Args:
            report: RCAReport to format
            scenario_id: Alert scenario identifier

        Returns:
            Dictionary conforming to the Datadog Events v1 schema
        """
        findings_text = (
            "\n".join(f"- {finding}" for finding in report.key_findings)
            if report.key_findings
            else "No specific findings recorded."
        )

        text_parts = []
        if report.blast_radius is not None:
            text_parts.append(format_blast_radius_card(report.blast_radius).strip())

        text_parts.append(report.investigation_summary)
        text_parts.append(f"Key Findings:\n{findings_text}")
        text = "\n\n".join(text_parts)

        return {
            "title": report.alert_name,
            "text": text,
            "tags": [
                "agent:incident-response",
                f"scenario:{scenario_id}",
                f"iterations:{report.iterations_used}",
            ],
            "alert_type": "info",
            "source_type_name": "incident-response-agent",
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff: 1s, 2s, 4s, …"""
    return _RETRY_BASE_DELAY * (2**attempt)
