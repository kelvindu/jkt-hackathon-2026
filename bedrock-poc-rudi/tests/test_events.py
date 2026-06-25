"""
Unit tests for DatadogEventsPublisher

Tests event formatting, API call logic, retry behaviour, and error handling
with mocked HTTP responses.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
"""

import sys
import os
from unittest.mock import Mock, patch, call, MagicMock

import pytest
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agent import RCAReport
from src.blast_radius import BlastRadiusCalculator
from src.config import AlertScenario
from src.events import DatadogEventsPublisher, _backoff_delay


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _report(
    alert_name: str = "High Error Rate",
    summary: str = "Payment gateway timed out causing 15% error rate.",
    findings: list[str] | None = None,
    iterations: int = 3,
) -> RCAReport:
    return RCAReport(
        alert_name=alert_name,
        investigation_summary=summary,
        key_findings=["Gateway timeout", "Deployment at 14:28"] if findings is None else findings,
        iterations_used=iterations,
        timestamp="2024-01-15T14:30:00Z",
    )


def _mock_response(status_code: int, json_data: dict | None = None) -> Mock:
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestDatadogEventsPublisherInit:
    def test_stores_api_key(self):
        pub = DatadogEventsPublisher(api_key="my-key")
        assert pub.api_key == "my-key"

    def test_default_site(self):
        pub = DatadogEventsPublisher(api_key="key")
        assert pub.site == "datadoghq.com"

    def test_custom_site(self):
        pub = DatadogEventsPublisher(api_key="key", site="datadoghq.eu")
        assert pub.site == "datadoghq.eu"
        assert "datadoghq.eu" in pub._api_url

    def test_api_url_construction(self):
        pub = DatadogEventsPublisher(api_key="key", site="datadoghq.com")
        assert pub._api_url == "https://api.datadoghq.com/api/v1/events"


# ---------------------------------------------------------------------------
# Event formatting
# ---------------------------------------------------------------------------


class TestFormatEvent:
    def test_title_is_alert_name(self):
        pub = DatadogEventsPublisher(api_key="key")
        payload = pub._format_event(_report(alert_name="DB Slowdown"), "db-slow")

        assert payload["title"] == "DB Slowdown"

    def test_text_includes_summary(self):
        pub = DatadogEventsPublisher(api_key="key")
        payload = pub._format_event(_report(summary="Root cause: OOM"), "s1")

        assert "Root cause: OOM" in payload["text"]

    def test_text_includes_key_findings(self):
        pub = DatadogEventsPublisher(api_key="key")
        payload = pub._format_event(
            _report(findings=["Memory spike", "No recent deploys"]), "s1"
        )

        assert "Memory spike" in payload["text"]
        assert "No recent deploys" in payload["text"]

    def test_text_includes_blast_radius_when_present(self):
        pub = DatadogEventsPublisher(api_key="key")
        report = _report(summary="Root cause confirmed.")
        report.blast_radius = BlastRadiusCalculator.compute_preliminary(
            AlertScenario(
                name="Checkout Error",
                description="desc",
                initial_context={
                    "service": "checkout-service",
                    "business_metrics": {
                        "stuck_customers": 42,
                        "financial_bleed_rate_usd_per_min": 145,
                    },
                },
                metadata={"severity": "high"},
            )
        )
        payload = pub._format_event(report, "s1")

        assert "WHAT BROKE" in payload["text"]
        assert "WHAT IT COSTS" in payload["text"]
        assert "Root cause confirmed." in payload["text"]

    def test_tags_include_agent_identifier(self):
        pub = DatadogEventsPublisher(api_key="key")
        payload = pub._format_event(_report(), "my-scenario")

        assert "agent:incident-response" in payload["tags"]

    def test_tags_include_scenario_id(self):
        pub = DatadogEventsPublisher(api_key="key")
        payload = pub._format_event(_report(), "checkout-errors")

        assert "scenario:checkout-errors" in payload["tags"]

    def test_tags_include_iterations(self):
        pub = DatadogEventsPublisher(api_key="key")
        payload = pub._format_event(_report(iterations=7), "s1")

        assert "iterations:7" in payload["tags"]

    def test_no_findings_uses_fallback_text(self):
        pub = DatadogEventsPublisher(api_key="key")
        payload = pub._format_event(_report(findings=[]), "s1")

        assert "No specific findings" in payload["text"]

    def test_alert_type_is_info(self):
        pub = DatadogEventsPublisher(api_key="key")
        payload = pub._format_event(_report(), "s1")

        assert payload["alert_type"] == "info"

    def test_source_type_name(self):
        pub = DatadogEventsPublisher(api_key="key")
        payload = pub._format_event(_report(), "s1")

        assert payload["source_type_name"] == "incident-response-agent"


# ---------------------------------------------------------------------------
# publish_rca — success path
# ---------------------------------------------------------------------------


class TestPublishRcaSuccess:
    @patch("src.events.requests.post")
    def test_returns_true_on_202(self, mock_post):
        mock_post.return_value = _mock_response(202)
        pub = DatadogEventsPublisher(api_key="key")

        result = pub.publish_rca(_report(), "s1")

        assert result is True

    @patch("src.events.requests.post")
    def test_posts_to_correct_url(self, mock_post):
        mock_post.return_value = _mock_response(202)
        pub = DatadogEventsPublisher(api_key="key", site="datadoghq.com")

        pub.publish_rca(_report(), "s1")

        assert mock_post.call_args[0][0] == "https://api.datadoghq.com/api/v1/events"

    @patch("src.events.requests.post")
    def test_sends_api_key_header(self, mock_post):
        mock_post.return_value = _mock_response(202)
        pub = DatadogEventsPublisher(api_key="test-key-123")

        pub.publish_rca(_report(), "s1")

        headers = mock_post.call_args[1]["headers"]
        assert headers["DD-API-KEY"] == "test-key-123"

    @patch("src.events.requests.post")
    def test_only_one_request_on_success(self, mock_post):
        mock_post.return_value = _mock_response(202)
        pub = DatadogEventsPublisher(api_key="key")

        pub.publish_rca(_report(), "s1")

        assert mock_post.call_count == 1


# ---------------------------------------------------------------------------
# publish_rca — auth failure
# ---------------------------------------------------------------------------


class TestPublishRcaAuthFailure:
    @patch("src.events.requests.post")
    def test_returns_false_on_403(self, mock_post):
        mock_post.return_value = _mock_response(403)
        pub = DatadogEventsPublisher(api_key="bad-key")

        result = pub.publish_rca(_report(), "s1")

        assert result is False

    @patch("src.events.requests.post")
    def test_no_retry_on_403(self, mock_post):
        mock_post.return_value = _mock_response(403)
        pub = DatadogEventsPublisher(api_key="bad-key")

        pub.publish_rca(_report(), "s1")

        assert mock_post.call_count == 1


# ---------------------------------------------------------------------------
# publish_rca — retry logic
# ---------------------------------------------------------------------------


class TestPublishRcaRetries:
    @patch("src.events.time.sleep")
    @patch("src.events.requests.post")
    def test_retries_on_network_error(self, mock_post, mock_sleep):
        mock_post.side_effect = [
            requests.ConnectionError("timeout"),
            requests.ConnectionError("timeout"),
            _mock_response(202),
        ]
        pub = DatadogEventsPublisher(api_key="key")

        result = pub.publish_rca(_report(), "s1")

        assert result is True
        assert mock_post.call_count == 3

    @patch("src.events.time.sleep")
    @patch("src.events.requests.post")
    def test_retries_on_rate_limit_429(self, mock_post, mock_sleep):
        mock_post.side_effect = [
            _mock_response(429),
            _mock_response(429),
            _mock_response(202),
        ]
        pub = DatadogEventsPublisher(api_key="key")

        result = pub.publish_rca(_report(), "s1")

        assert result is True
        assert mock_post.call_count == 3

    @patch("src.events.time.sleep")
    @patch("src.events.requests.post")
    def test_returns_false_after_max_retries(self, mock_post, mock_sleep):
        mock_post.side_effect = requests.ConnectionError("down")
        pub = DatadogEventsPublisher(api_key="key")

        result = pub.publish_rca(_report(), "s1")

        assert result is False
        assert mock_post.call_count == 3  # MAX_RETRIES

    @patch("src.events.time.sleep")
    @patch("src.events.requests.post")
    def test_exponential_backoff_delays(self, mock_post, mock_sleep):
        mock_post.side_effect = [
            requests.ConnectionError("e"),
            requests.ConnectionError("e"),
            requests.ConnectionError("e"),
        ]
        pub = DatadogEventsPublisher(api_key="key")

        pub.publish_rca(_report(), "s1")

        # Two sleeps for 3 attempts (last attempt has no sleep)
        assert mock_sleep.call_count == 2
        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert delays[1] > delays[0], "Backoff should increase"

    @patch("src.events.requests.post")
    def test_request_exception_returns_false_immediately(self, mock_post):
        mock_post.side_effect = requests.RequestException("fatal")
        pub = DatadogEventsPublisher(api_key="key")

        result = pub.publish_rca(_report(), "s1")

        assert result is False
        assert mock_post.call_count == 1


# ---------------------------------------------------------------------------
# Backoff helper
# ---------------------------------------------------------------------------


class TestBackoffDelay:
    def test_doubles_each_attempt(self):
        assert _backoff_delay(0) == 1.0
        assert _backoff_delay(1) == 2.0
        assert _backoff_delay(2) == 4.0
