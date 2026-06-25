"""Tests for ``enable_llmobs`` and ``flush`` in :mod:`track_aiops.observability`.

Covers the enable and flush behavior:

- ``enable_llmobs`` calls ``LLMObs.enable`` in agentless mode with the
  configured ml_app, API key, and site (Requirement 4.1).
- ``enable_llmobs`` is idempotent: calling it multiple times does not raise or
  re-enable LLMObs (Property 5: Idempotent Enable).
- ``flush`` calls ``LLMObs.flush`` (Requirement 4.4).

Requirements: 4.1, 4.4
"""

from unittest.mock import patch

import pytest

from track_aiops import observability
from track_aiops.config import Settings


def make_settings() -> Settings:
    """Build a Settings instance with sample values for the tests."""
    return Settings(
        dd_api_key="test-api-key",
        dd_site="datadoghq.eu",
        dd_llmobs_ml_app="test-ml-app",
        aws_region="us-east-1",
        model_id="amazon.nova-pro-v1:0",
        model_name="nova-pro",
        model_provider="bedrock",
    )


@pytest.fixture(autouse=True)
def reset_enabled_guard(monkeypatch):
    """Reset the module-level guard before each test for determinism.

    ``enable_llmobs`` short-circuits when ``_enabled`` is True, so the
    idempotency tests must start from a known ``False`` state.
    """
    monkeypatch.setattr(observability, "_enabled", False)


# --- enable_llmobs ----------------------------------------------------------


def test_enable_llmobs_calls_enable_with_agentless_and_config():
    """``enable_llmobs`` enables LLMObs in agentless mode with correct config.

    **Validates: Requirements 4.1**
    """
    settings = make_settings()

    with patch.object(observability, "LLMObs") as mock_llmobs:
        observability.enable_llmobs(settings)

    mock_llmobs.enable.assert_called_once_with(
        ml_app="test-ml-app",
        agentless_enabled=True,
        api_key="test-api-key",
        site="datadoghq.eu",
    )


def test_enable_llmobs_is_idempotent():
    """Calling ``enable_llmobs`` multiple times does not raise or re-enable.

    **Validates: Requirements 4.1**
    """
    settings = make_settings()

    with patch.object(observability, "LLMObs") as mock_llmobs:
        observability.enable_llmobs(settings)
        observability.enable_llmobs(settings)
        observability.enable_llmobs(settings)

    # The guard ensures enable side effects happen exactly once.
    mock_llmobs.enable.assert_called_once()


# --- flush ------------------------------------------------------------------


def test_flush_calls_llmobs_flush():
    """``flush`` delegates to ``LLMObs.flush``.

    **Validates: Requirements 4.4**
    """
    with patch.object(observability, "LLMObs") as mock_llmobs:
        observability.flush()

    mock_llmobs.flush.assert_called_once_with()
