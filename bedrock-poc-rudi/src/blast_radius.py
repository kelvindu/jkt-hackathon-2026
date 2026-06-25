"""
Financial Blast Radius Copilot module.

Produces a unified narrative answering:
  1. WHAT BROKE  — technical root cause (suspected → confirmed)
  2. WHAT IT COSTS — customer impact + financial bleed rate + runbook savings

Business numbers are simulated from alert metrics (formula-based).
Technical cause is confirmed by the Bedrock investigation loop.
"""

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

from .config import AlertScenario

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Runbook catalog keyed by service
# ---------------------------------------------------------------------------

RUNBOOKS: dict[str, dict[str, Any]] = {
    "checkout-service": {
        "title": "Route traffic to backup database",
        "action": "Failover checkout DB read replica and drain connection pool",
        "estimated_savings_usd": 2000,
    },
    "orders-service": {
        "title": "Scale order workers and enable request batching",
        "action": "Increase worker pool and switch to batched line-item API",
        "estimated_savings_usd": 1500,
    },
    "default": {
        "title": "Execute standard incident runbook",
        "action": "Follow on-call runbook for service failover and traffic shedding",
        "estimated_savings_usd": 1000,
    },
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TechnicalImpact:
    """What broke — technical root cause and affected components."""

    service: str
    endpoint: str
    error_codes: list[str]
    suspected_root_cause: str
    confirmed_root_cause: str = ""
    affected_file: str = ""
    symptoms: list[str] = field(default_factory=list)
    fix_pr_url: str = ""
    status: str = "suspected"  # "suspected" | "confirmed"


@dataclass
class BusinessImpact:
    """What it costs — customer and financial impact."""

    affected_customers: int
    affected_services: list[str]
    financial_bleed_rate_usd_per_min: float
    estimated_loss_next_30_min_usd: float
    recommended_runbook_title: str
    recommended_runbook_action: str
    recommended_runbook_url: str
    runbook_estimated_savings_usd: float
    data_source: str = "simulated"


@dataclass
class BlastRadiusReport:
    """Unified blast-radius output combining technical + business impact."""

    alert_title: str
    severity: str
    technical: TechnicalImpact
    business: BusinessImpact

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_title": self.alert_title,
            "severity": self.severity,
            "technical": asdict(self.technical),
            "business": asdict(self.business),
        }


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------


class BlastRadiusCalculator:
    """Compute preliminary and final blast-radius reports from alert scenarios."""

    @classmethod
    def compute_preliminary(cls, scenario: AlertScenario) -> BlastRadiusReport:
        ctx = scenario.initial_context if isinstance(scenario.initial_context, dict) else {}
        technical = cls._build_technical(ctx, scenario.description)
        business = cls._build_business(ctx, scenario.metadata, technical.service)
        severity = cls._map_severity(scenario.metadata.get("severity", "high"))
        return BlastRadiusReport(
            alert_title=scenario.name,
            severity=severity,
            technical=technical,
            business=business,
        )

    @classmethod
    def merge_final(
        cls,
        preliminary: BlastRadiusReport,
        messages: list[dict[str, Any]],
        investigation_summary: str,
    ) -> BlastRadiusReport:
        """Promote suspected → confirmed using investigation results."""
        confirmed = investigation_summary.strip() or preliminary.technical.suspected_root_cause
        pr_url = cls._extract_pr_url(messages)

        technical = TechnicalImpact(
            service=preliminary.technical.service,
            endpoint=preliminary.technical.endpoint,
            error_codes=preliminary.technical.error_codes,
            suspected_root_cause=preliminary.technical.suspected_root_cause,
            confirmed_root_cause=confirmed,
            affected_file=preliminary.technical.affected_file,
            symptoms=preliminary.technical.symptoms,
            fix_pr_url=pr_url,
            status="confirmed",
        )

        return BlastRadiusReport(
            alert_title=preliminary.alert_title,
            severity=preliminary.severity,
            technical=technical,
            business=preliminary.business,
        )

    @classmethod
    def _build_technical(cls, ctx: dict[str, Any], description: str) -> TechnicalImpact:
        suspected = ctx.get("suspected_technical_cause", "")
        if not suspected:
            parts = []
            for key in ("incident_43_issue", "incident_13_issue"):
                if ctx.get(key):
                    parts.append(str(ctx[key]))
            suspected = " ".join(parts) if parts else description

        error_codes = ctx.get("error_codes", [])
        if isinstance(error_codes, str):
            error_codes = [error_codes]

        symptoms = ctx.get("symptoms", [])
        if isinstance(symptoms, str):
            symptoms = [symptoms]

        return TechnicalImpact(
            service=str(ctx.get("service", "unknown-service")),
            endpoint=str(ctx.get("endpoint", "")),
            error_codes=error_codes,
            suspected_root_cause=suspected,
            affected_file=str(ctx.get("suspected_file", "")),
            symptoms=symptoms,
            status="suspected",
        )

    @classmethod
    def _build_business(
        cls,
        ctx: dict[str, Any],
        metadata: dict[str, Any],
        service: str,
    ) -> BusinessImpact:
        metrics = ctx.get("business_metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}

        stuck, data_source = cls._resolve_stuck_customers(ctx, metrics, service)
        avg_order = float(
            metrics.get("avg_order_value_usd")
            or os.getenv("AVG_ORDER_VALUE_USD", "29.99")
        )
        attempts = float(
            metrics.get("checkout_attempts_per_min")
            or os.getenv("CHECKOUT_ATTEMPTS_PER_CUSTOMER_PER_MIN", "0.35")
        )

        bleed_explicit = metrics.get("financial_bleed_rate_usd_per_min")
        if bleed_explicit is not None:
            bleed_per_min = float(bleed_explicit)
        else:
            bleed_per_min = round(stuck * avg_order * attempts, 2)

        loss_30 = round(bleed_per_min * 30, 2)

        runbook = RUNBOOKS.get(service, RUNBOOKS["default"])
        savings_explicit = metrics.get("runbook_savings_usd")
        savings = float(savings_explicit) if savings_explicit is not None else float(
            runbook.get("estimated_savings_usd", 1000)
        )

        if not savings_explicit:
            mttr_min = float(os.getenv("RUNBOOK_MTTR_SAVINGS_MINUTES", "14"))
            savings = round(bleed_per_min * mttr_min, 2)

        runbook_url = str(metadata.get("runbook", ""))

        return BusinessImpact(
            affected_customers=stuck,
            affected_services=[service] if service else [],
            financial_bleed_rate_usd_per_min=bleed_per_min,
            estimated_loss_next_30_min_usd=loss_30,
            recommended_runbook_title=str(runbook.get("title", "Execute incident runbook")),
            recommended_runbook_action=str(runbook.get("action", "")),
            recommended_runbook_url=runbook_url,
            runbook_estimated_savings_usd=savings,
            data_source=data_source,
        )

    @classmethod
    def _resolve_stuck_customers(
        cls,
        ctx: dict[str, Any],
        metrics: dict[str, Any],
        service: str,
    ) -> tuple[int, str]:
        if metrics.get("stuck_customers") is not None:
            return int(metrics["stuck_customers"]), "simulated"

        dd_count = cls._query_datadog_error_count(service)
        if dd_count is not None:
            return dd_count, "datadog"

        affected_raw = str(ctx.get("affected_users", "0")).replace("~", "").strip()
        try:
            affected = int(re.sub(r"[^\d]", "", affected_raw) or "0")
        except ValueError:
            affected = 0

        error_rate_str = str(ctx.get("error_rate_current", "0")).replace("%", "").strip()
        try:
            error_rate = float(error_rate_str) / 100.0
        except ValueError:
            error_rate = 0.15

        return max(1, int(affected * error_rate)) if affected else 42, "simulated"

    @classmethod
    def _query_datadog_error_count(cls, service: str) -> Optional[int]:
        api_key = os.getenv("DD_API_KEY", "")
        app_key = os.getenv("DD_APP_KEY", "")
        if not api_key or not app_key or not service:
            return None

        site = os.getenv("DD_SITE", "datadoghq.com")
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=15)

        query = f"sum:trace.http.request.errors{{service:{service}}}.as_count()"
        params = {
            "from": int(start.timestamp()),
            "to": int(end.timestamp()),
            "query": query,
        }

        try:
            resp = requests.get(
                f"https://api.{site}/api/v1/query",
                params=params,
                headers={
                    "DD-API-KEY": api_key,
                    "DD-APPLICATION-KEY": app_key,
                },
                timeout=10,
            )
            if resp.status_code != 200:
                return None
            series = resp.json().get("series", [])
            if not series:
                return None
            points = series[0].get("pointlist", [])
            total = sum(p[1] for p in points if p[1] is not None)
            return max(1, int(total)) if total > 0 else None
        except requests.RequestException as exc:
            logger.debug("Datadog metrics enrichment skipped: %s", exc)
            return None

    @classmethod
    def _extract_pr_url(cls, messages: list[dict[str, Any]]) -> str:
        for msg in messages:
            if msg.get("role") != "user":
                continue
            for block in msg.get("content", []):
                if "toolResult" not in block:
                    continue
                for item in block["toolResult"].get("content", []):
                    payload = item.get("json") or item.get("text")
                    if isinstance(payload, dict) and payload.get("pr_url"):
                        return str(payload["pr_url"])
                    if isinstance(payload, str):
                        match = re.search(r"https://github\.com/\S+/pull/\d+", payload)
                        if match:
                            return match.group(0)
        for msg in reversed(messages):
            if msg.get("role") != "assistant":
                continue
            for block in msg.get("content", []):
                text = block.get("text", "")
                match = re.search(r"Fix PR:\s*(https://github\.com/\S+)", text)
                if match:
                    return match.group(1)
                match = re.search(r"https://github\.com/\S+/pull/\d+", text)
                if match:
                    return match.group(0)
        return ""

    @classmethod
    def _map_severity(cls, raw: str) -> str:
        mapping = {
            "critical": "Critical",
            "high": "High",
            "medium": "Medium",
            "low": "Low",
        }
        return mapping.get(str(raw).lower(), "High")


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_blast_radius_card(report: BlastRadiusReport) -> str:
    """Return judge-friendly multi-line card with WHAT BROKE + WHAT IT COSTS."""
    t = report.technical
    b = report.business

    root_cause = t.confirmed_root_cause if t.status == "confirmed" and t.confirmed_root_cause else t.suspected_root_cause
    status_label = "CONFIRMED" if t.status == "confirmed" else "SUSPECTED"

    lines = [
        "",
        "=" * 42,
        "  FINANCIAL BLAST RADIUS COPILOT",
        "=" * 42,
        "",
        f"🚨 {report.severity} Alert: {report.alert_title}",
        "",
        "WHAT BROKE",
        f"  Status:      {status_label}",
        f"  Service:     {t.service}" + (f" ({t.endpoint})" if t.endpoint else ""),
    ]

    if t.affected_file:
        lines.append(f"  File:        {t.affected_file}")
    if t.error_codes:
        lines.append(f"  Error codes: {', '.join(t.error_codes)}")
    if t.symptoms:
        lines.append(f"  Symptoms:    {'; '.join(t.symptoms[:3])}")

    lines.append(f"  Root cause:  {root_cause}")

    if t.fix_pr_url:
        lines.append(f"  Fix PR:      {t.fix_pr_url}")

    lines.extend([
        "",
        "WHAT IT COSTS",
        f"  Customers stuck right now:     {b.affected_customers}",
        f"  Financial bleed rate:        ${b.financial_bleed_rate_usd_per_min:,.0f}/min",
        f"  Projected loss (30 min):       ${b.estimated_loss_next_30_min_usd:,.0f}",
        f"  Data source:                 {b.data_source}",
        "",
        "RECOMMENDED ACTION",
        f"  Runbook: {b.recommended_runbook_title}",
        f"  Action:  {b.recommended_runbook_action}",
    ])

    if b.recommended_runbook_url:
        lines.append(f"  URL:     {b.recommended_runbook_url}")

    lines.append(
        f"  Estimated savings if applied now: ~${b.runbook_estimated_savings_usd:,.0f}"
    )
    lines.append("")
    lines.append("=" * 42)
    lines.append("")

    return "\n".join(lines)


def format_blast_radius_context(report: BlastRadiusReport) -> str:
    """Short block injected into the Bedrock initial prompt."""
    t = report.technical
    b = report.business
    return (
        "BLAST RADIUS CONTEXT (use these numbers in your final summary — do NOT invent):\n"
        f"WHAT BROKE (suspected): {t.suspected_root_cause}\n"
        f"WHAT IT COSTS: {b.affected_customers} customers stuck, "
        f"${b.financial_bleed_rate_usd_per_min:,.0f}/min bleed rate, "
        f"${b.estimated_loss_next_30_min_usd:,.0f} projected loss over 30 min\n"
        f"RECOMMENDED ACTION: {b.recommended_runbook_title} "
        f"(saves ~${b.runbook_estimated_savings_usd:,.0f})"
    )
