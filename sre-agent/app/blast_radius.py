"""Financial Blast Radius Copilot.

Produces a judge-friendly WHAT BROKE / WHAT IT COSTS / RECOMMENDED ACTION card.
Business dollar figures are computed by formula from alert metrics — never by the
LLM — so the numbers are defensible. Computed instantly (before any model call)
as SUSPECTED, then promoted to CONFIRMED after the investigation.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

RUNBOOKS: dict[str, dict[str, Any]] = {
    "auth-service": {
        "title": "Disable fault injection & drain connection pool",
        "action": "POST /api/v1/admin/chaos/deactivate, then recycle DB connection pool",
        "estimated_savings_usd": 1800,
    },
    "default": {
        "title": "Execute standard incident runbook",
        "action": "Follow on-call runbook for service failover and traffic shedding",
        "estimated_savings_usd": 1000,
    },
}


@dataclass
class TechnicalImpact:
    service: str
    endpoint: str
    error_codes: list[str]
    suspected_root_cause: str
    confirmed_root_cause: str = ""
    affected_file: str = ""
    symptoms: list[str] = field(default_factory=list)
    remediation_applied: str = ""
    status: str = "suspected"  # "suspected" | "confirmed"


@dataclass
class BusinessImpact:
    affected_customers: int
    financial_bleed_rate_usd_per_min: float
    estimated_loss_next_30_min_usd: float
    recommended_runbook_title: str
    recommended_runbook_action: str
    runbook_estimated_savings_usd: float
    data_source: str = "simulated"


@dataclass
class BlastRadiusReport:
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


class BlastRadiusCalculator:
    @classmethod
    def compute_preliminary(cls, scenario: "Any") -> BlastRadiusReport:
        ctx = scenario.initial_context if isinstance(scenario.initial_context, dict) else {}
        technical = cls._technical(ctx, scenario.description)
        business = cls._business(ctx, technical.service)
        return BlastRadiusReport(
            alert_title=scenario.name,
            severity=cls._severity(scenario.metadata.get("severity", "high")),
            technical=technical,
            business=business,
        )

    @classmethod
    def merge_final(
        cls,
        preliminary: BlastRadiusReport,
        confirmed_cause: str,
        remediation_applied: str = "",
    ) -> BlastRadiusReport:
        t = preliminary.technical
        technical = TechnicalImpact(
            service=t.service,
            endpoint=t.endpoint,
            error_codes=t.error_codes,
            suspected_root_cause=t.suspected_root_cause,
            confirmed_root_cause=(confirmed_cause.strip() or t.suspected_root_cause),
            affected_file=t.affected_file,
            symptoms=t.symptoms,
            remediation_applied=remediation_applied,
            status="confirmed",
        )
        return BlastRadiusReport(
            alert_title=preliminary.alert_title,
            severity=preliminary.severity,
            technical=technical,
            business=preliminary.business,
        )

    @classmethod
    def _technical(cls, ctx: dict[str, Any], description: str) -> TechnicalImpact:
        error_codes = ctx.get("error_codes", [])
        if isinstance(error_codes, str):
            error_codes = [error_codes]
        symptoms = ctx.get("symptoms", [])
        if isinstance(symptoms, str):
            symptoms = [symptoms]
        return TechnicalImpact(
            service=str(ctx.get("service", "auth-service")),
            endpoint=str(ctx.get("endpoint", "")),
            error_codes=error_codes,
            suspected_root_cause=str(ctx.get("suspected_technical_cause", description)),
            affected_file=str(ctx.get("suspected_file", "")),
            symptoms=symptoms,
        )

    @classmethod
    def _business(cls, ctx: dict[str, Any], service: str) -> BusinessImpact:
        metrics = ctx.get("business_metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}
        stuck = int(metrics.get("stuck_customers", 42))
        bleed = metrics.get("financial_bleed_rate_usd_per_min")
        if bleed is None:
            avg_order = float(os.getenv("AVG_ORDER_VALUE_USD", "29.99"))
            attempts = float(os.getenv("CHECKOUT_ATTEMPTS_PER_CUSTOMER_PER_MIN", "0.35"))
            bleed = round(stuck * avg_order * attempts, 2)
        bleed = float(bleed)
        runbook = RUNBOOKS.get(service, RUNBOOKS["default"])
        savings = float(metrics.get("runbook_savings_usd", runbook["estimated_savings_usd"]))
        return BusinessImpact(
            affected_customers=stuck,
            financial_bleed_rate_usd_per_min=bleed,
            estimated_loss_next_30_min_usd=round(bleed * 30, 2),
            recommended_runbook_title=str(runbook["title"]),
            recommended_runbook_action=str(runbook["action"]),
            runbook_estimated_savings_usd=savings,
            data_source=str(metrics.get("data_source", "simulated")),
        )

    @staticmethod
    def _severity(raw: str) -> str:
        return {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}.get(
            str(raw).lower(), "High"
        )


def format_blast_radius_card(report: BlastRadiusReport) -> str:
    t, b = report.technical, report.business
    root = t.confirmed_root_cause if t.status == "confirmed" and t.confirmed_root_cause else t.suspected_root_cause
    status = "CONFIRMED" if t.status == "confirmed" else "SUSPECTED"
    lines = [
        "",
        "=" * 46,
        "  FINANCIAL BLAST RADIUS COPILOT",
        "=" * 46,
        "",
        f"🚨 {report.severity} Alert: {report.alert_title}",
        "",
        "WHAT BROKE",
        f"  Status:      {status}",
        f"  Service:     {t.service}" + (f" ({t.endpoint})" if t.endpoint else ""),
    ]
    if t.affected_file:
        lines.append(f"  File:        {t.affected_file}")
    if t.error_codes:
        lines.append(f"  Error codes: {', '.join(t.error_codes)}")
    if t.symptoms:
        lines.append(f"  Symptoms:    {'; '.join(t.symptoms[:3])}")
    lines.append(f"  Root cause:  {root}")
    if t.remediation_applied:
        lines.append(f"  Remediation: {t.remediation_applied}")
    lines += [
        "",
        "WHAT IT COSTS",
        f"  Customers stuck right now:   {b.affected_customers}",
        f"  Financial bleed rate:        ${b.financial_bleed_rate_usd_per_min:,.0f}/min",
        f"  Projected loss (30 min):     ${b.estimated_loss_next_30_min_usd:,.0f}",
        f"  Data source:                 {b.data_source}",
        "",
        "RECOMMENDED ACTION",
        f"  Runbook: {b.recommended_runbook_title}",
        f"  Action:  {b.recommended_runbook_action}",
        f"  Estimated savings if applied now: ~${b.runbook_estimated_savings_usd:,.0f}",
        "",
        "=" * 46,
        "",
    ]
    return "\n".join(lines)


def format_blast_radius_context(report: BlastRadiusReport) -> str:
    t, b = report.technical, report.business
    return (
        "BLAST RADIUS CONTEXT (use these numbers verbatim in your final summary — do NOT invent):\n"
        f"WHAT BROKE (suspected): {t.suspected_root_cause}\n"
        f"WHAT IT COSTS: {b.affected_customers} customers stuck, "
        f"${b.financial_bleed_rate_usd_per_min:,.0f}/min bleed, "
        f"${b.estimated_loss_next_30_min_usd:,.0f} projected loss over 30 min\n"
        f"RECOMMENDED ACTION: {b.recommended_runbook_title} (saves ~${b.runbook_estimated_savings_usd:,.0f})"
    )
