"""High-level orchestration shared by the webhook server and the CLI.

Ties together: enable observability → run the investigation → publish the RCA →
flush spans. Keeps :mod:`app.server` and :mod:`app.main` thin.
"""

from __future__ import annotations

import logging

from . import observability as obs
from .agent import InvestigationAgent, RCAReport
from .bedrock_client import BedrockClient
from .chat_notifier import GoogleChatNotifier
from .config import Settings
from .events import DatadogEventsPublisher
from .scenarios import AlertScenario

logger = logging.getLogger(__name__)


def run_investigation(scenario: AlertScenario, settings: Settings) -> tuple[RCAReport, bool]:
    """Investigate ``scenario``, publish the RCA, and notify Google Chat.

    Returns (report, published) where ``published`` is the Datadog Events result.
    Spans are flushed before returning so a short-lived process (CLI / serverless
    request) still ships its trace to Datadog.
    """
    obs.enable(settings)
    try:
        agent = InvestigationAgent(BedrockClient(region=settings.aws_region, model_id=settings.model_id), settings)
        report = agent.investigate(scenario)

        published = DatadogEventsPublisher(settings.dd_api_key, settings.dd_site).publish_rca(
            report, scenario.scenario_id
        )
        # Push the RCA to the on-call Google Chat space (best-effort).
        GoogleChatNotifier(settings.google_chat_webhook_url).post_rca(report, scenario.scenario_id)
        return report, published
    finally:
        obs.flush()
