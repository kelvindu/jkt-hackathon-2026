"""Google Chat notifier — pushes the RCA to a Chat space via incoming webhook.

The webhook URL (which embeds a key + token) is read from the
``GOOGLE_CHAT_WEBHOOK_URL`` env var so it is never hard-coded. The RCA is sent as
a Google Chat ``cardsV2`` message (WHAT BROKE / WHAT IT COSTS / ACTION + the
observability footprint), with a plain-text fallback for resilience.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from .agent import RCAReport

logger = logging.getLogger(__name__)

_TIMEOUT = 15


class GoogleChatNotifier:
    """Posts RCA reports to a Google Chat space."""

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def post_rca(self, report: "RCAReport", scenario_id: str) -> bool:
        """Send the RCA card. Returns True on a 2xx, False otherwise (never raises)."""
        if not self.enabled:
            logger.info(json.dumps({"event": "chat.skipped", "reason": "no GOOGLE_CHAT_WEBHOOK_URL"}))
            return False
        try:
            resp = requests.post(
                self.webhook_url,
                json=self._build_card(report, scenario_id),
                headers={"Content-Type": "application/json; charset=UTF-8"},
                timeout=_TIMEOUT,
            )
            ok = 200 <= resp.status_code < 300
            logger.info(
                json.dumps({"event": "chat.posted" if ok else "chat.error", "status": resp.status_code})
            )
            return ok
        except requests.RequestException as exc:
            logger.error(json.dumps({"event": "chat.request_error", "error": str(exc)}))
            return False

    # ------------------------------------------------------------------

    def _build_card(self, report: "RCAReport", scenario_id: str) -> dict[str, Any]:
        remediated = "✅ Auto-remediated" if report.remediated else "⚠️ Manual action required"
        br = report.blast_radius
        what_broke = "—"
        cost_line = "—"
        action_line = "—"
        severity = "High"
        monitor_url = ""
        if br is not None:
            severity = br.severity
            t, b = br.technical, br.business
            what_broke = t.confirmed_root_cause or t.suspected_root_cause
            if t.affected_file:
                what_broke += f"\n<b>File:</b> {t.affected_file}"
            cost_line = (
                f"{b.affected_customers} customers stuck • "
                f"${b.financial_bleed_rate_usd_per_min:,.0f}/min • "
                f"${b.estimated_loss_next_30_min_usd:,.0f} over 30 min"
            )
            action_line = f"{b.recommended_runbook_title} (saves ~${b.runbook_estimated_savings_usd:,.0f})"

        widgets = [
            _decorated("🧨 WHAT BROKE", _truncate(what_broke, 800)),
            _decorated("💸 WHAT IT COSTS", cost_line),
            _decorated("🛠️ RECOMMENDED ACTION", action_line),
            _decorated("🤖 Remediation", remediated),
            _decorated(
                "📊 Observability",
                f"{report.iterations_used} reasoning steps • "
                f"{report.total_tokens:,} tokens • ${report.total_cost_usd:.4f} • Nova Pro",
            ),
        ]
        card: dict[str, Any] = {
            "header": {
                "title": f"🚨 {severity} — SRE Agent RCA",
                "subtitle": report.alert_name,
                "imageUrl": "https://datadog-prod.imgix.net/img/dd_logo_70x75.png",
                "imageType": "CIRCLE",
            },
            "sections": [{"widgets": widgets}],
        }
        if monitor_url:
            card["sections"].append(
                {"widgets": [{"buttonList": {"buttons": [{"text": "Open Monitor", "onClick": {"openLink": {"url": monitor_url}}}]}}]}
            )

        return {
            # Plain-text fallback (also used in notifications/preview).
            "text": f"*[SRE Agent] RCA: {report.alert_name}*\n{report.investigation_summary[:1500]}",
            "cardsV2": [{"cardId": f"rca-{scenario_id}", "card": card}],
        }


def _decorated(top_label: str, text: str) -> dict[str, Any]:
    return {"decoratedText": {"topLabel": top_label, "text": text or "—", "wrapText": True}}


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
