"""
Unit tests for Financial Blast Radius Copilot module.
"""

import os
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.blast_radius import (
    BlastRadiusCalculator,
    format_blast_radius_card,
    format_blast_radius_context,
)
from src.config import AlertScenario


def _checkout_scenario(
    business_metrics: dict | None = None,
    suspected_cause: str = "",
) -> AlertScenario:
    ctx: dict = {
        "service": "checkout-service",
        "endpoint": "/api/checkout",
        "error_codes": ["502", "504"],
        "suspected_file": "services/orders.py",
        "symptoms": ["Connection pool exhausted", "p95 latency 10x"],
        "affected_users": "~500",
        "error_rate_current": "15%",
        "incident_43_issue": "missing HTTP timeouts",
        "incident_13_issue": "N+1 HTTP pattern",
    }
    if suspected_cause:
        ctx["suspected_technical_cause"] = suspected_cause
    if business_metrics:
        ctx["business_metrics"] = business_metrics

    return AlertScenario(
        name="Checkout API Error Spike",
        description="Error rate jumped to 15%",
        initial_context=ctx,
        metadata={"severity": "high", "runbook": "https://wiki.example.com/runbooks/checkout"},
    )


class TestComputePreliminary:
    def test_card_contains_what_broke_and_what_it_costs(self):
        scenario = _checkout_scenario(
            business_metrics={
                "stuck_customers": 42,
                "financial_bleed_rate_usd_per_min": 145,
                "runbook_savings_usd": 2000,
            },
            suspected_cause="N+1 HTTP + missing timeouts in services/orders.py",
        )
        report = BlastRadiusCalculator.compute_preliminary(scenario)
        card = format_blast_radius_card(report)

        assert "WHAT BROKE" in card
        assert "WHAT IT COSTS" in card
        assert "RECOMMENDED ACTION" in card
        assert "SUSPECTED" in card
        assert "checkout-service" in card
        assert "42" in card
        assert "$145" in card
        assert "N+1 HTTP" in card

    def test_explicit_business_metrics_override_formula(self):
        scenario = _checkout_scenario(
            business_metrics={
                "stuck_customers": 99,
                "avg_order_value_usd": 50.0,
                "checkout_attempts_per_min": 0.5,
                "financial_bleed_rate_usd_per_min": 500,
                "runbook_savings_usd": 3000,
            }
        )
        report = BlastRadiusCalculator.compute_preliminary(scenario)

        assert report.business.affected_customers == 99
        assert report.business.financial_bleed_rate_usd_per_min == 500.0
        assert report.business.estimated_loss_next_30_min_usd == 15000.0
        assert report.business.runbook_estimated_savings_usd == 3000.0
        assert report.business.data_source == "simulated"

    def test_formula_when_no_explicit_bleed_rate(self):
        scenario = _checkout_scenario(
            business_metrics={
                "stuck_customers": 10,
                "avg_order_value_usd": 20.0,
                "checkout_attempts_per_min": 0.5,
            }
        )
        report = BlastRadiusCalculator.compute_preliminary(scenario)

        assert report.business.financial_bleed_rate_usd_per_min == 100.0
        assert report.business.estimated_loss_next_30_min_usd == 3000.0

    def test_suspected_cause_from_incident_issues_when_not_explicit(self):
        scenario = _checkout_scenario()
        report = BlastRadiusCalculator.compute_preliminary(scenario)

        assert "missing HTTP timeouts" in report.technical.suspected_root_cause
        assert "N+1 HTTP pattern" in report.technical.suspected_root_cause
        assert report.technical.status == "suspected"

    def test_blast_radius_context_for_prompt_injection(self):
        scenario = _checkout_scenario(
            business_metrics={"stuck_customers": 42, "financial_bleed_rate_usd_per_min": 145},
            suspected_cause="Pool exhaustion in orders.py",
        )
        report = BlastRadiusCalculator.compute_preliminary(scenario)
        ctx = format_blast_radius_context(report)

        assert "BLAST RADIUS CONTEXT" in ctx
        assert "do NOT invent" in ctx
        assert "42 customers stuck" in ctx
        assert "$145" in ctx


class TestMergeFinal:
    def test_promotes_suspected_to_confirmed(self):
        preliminary = BlastRadiusCalculator.compute_preliminary(
            _checkout_scenario(
                business_metrics={"stuck_customers": 42, "financial_bleed_rate_usd_per_min": 145},
                suspected_cause="Suspected N+1 pattern",
            )
        )
        messages = [
            {
                "role": "assistant",
                "content": [{"text": "WHAT BROKE: Confirmed N+1 in services/orders.py"}],
            }
        ]
        final = BlastRadiusCalculator.merge_final(
            preliminary,
            messages,
            "WHAT BROKE: Confirmed N+1 in services/orders.py",
        )

        assert final.technical.status == "confirmed"
        assert "Confirmed N+1" in final.technical.confirmed_root_cause
        assert final.business.affected_customers == 42
        assert final.business.financial_bleed_rate_usd_per_min == 145.0

    def test_extracts_pr_url_from_tool_result(self):
        preliminary = BlastRadiusCalculator.compute_preliminary(_checkout_scenario())
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "content": [
                                {
                                    "json": {
                                        "pr_url": "https://github.com/owner/repo/pull/42"
                                    }
                                }
                            ]
                        }
                    }
                ],
            }
        ]
        final = BlastRadiusCalculator.merge_final(
            preliminary, messages, "Root cause confirmed."
        )

        assert final.technical.fix_pr_url == "https://github.com/owner/repo/pull/42"
        card = format_blast_radius_card(final)
        assert "pull/42" in card
        assert "CONFIRMED" in card


class TestDatadogEnrichment:
    @patch.dict(os.environ, {"DD_API_KEY": "key", "DD_APP_KEY": "app"}, clear=False)
    @patch("src.blast_radius.requests.get")
    def test_datadog_fallback_enriches_stuck_customers(self, mock_get):
        mock_get.return_value = Mock(
            status_code=200,
            json=lambda: {"series": [{"pointlist": [[0, 55.0], [1, 45.0]]}]},
        )
        scenario = AlertScenario(
            name="Test",
            description="desc",
            initial_context={"service": "checkout-service"},
            metadata={"severity": "high"},
        )
        report = BlastRadiusCalculator.compute_preliminary(scenario)

        assert report.business.affected_customers == 100
        assert report.business.data_source == "datadog"

    @patch.dict(os.environ, {}, clear=True)
    def test_simulated_fallback_without_datadog_keys(self):
        scenario = AlertScenario(
            name="Test",
            description="desc",
            initial_context={
                "service": "checkout-service",
                "affected_users": "100",
                "error_rate_current": "10%",
            },
            metadata={"severity": "high"},
        )
        report = BlastRadiusCalculator.compute_preliminary(scenario)

        assert report.business.affected_customers == 10
        assert report.business.data_source == "simulated"


class TestToDict:
    def test_blast_radius_report_serializes(self):
        report = BlastRadiusCalculator.compute_preliminary(
            _checkout_scenario(
                business_metrics={"stuck_customers": 42, "financial_bleed_rate_usd_per_min": 145}
            )
        )
        data = report.to_dict()

        assert data["alert_title"] == "Checkout API Error Spike"
        assert data["technical"]["service"] == "checkout-service"
        assert data["business"]["affected_customers"] == 42
