"""Tests for :mod:`track_aiops.config`.

Covers fail-fast validation of required environment variables, including the
property-based guarantee that any non-empty subset of removed required
variables causes ``load()`` to raise an error naming at least one of them.

Property 4 (Missing required config raises with exact variable name)
"""

import os
from contextlib import contextmanager

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from track_aiops import config
from track_aiops.config import REQUIRED_ENV_VARS

# Optional vars that have defaults; included so a complete-but-for-removed env
# can be constructed without accidentally tripping over them.
OPTIONAL_ENV_VARS = ("DD_SITE", "AWS_REGION")

# A non-empty placeholder value for every variable we control during a test.
ALL_CONTROLLED_VARS = REQUIRED_ENV_VARS + OPTIONAL_ENV_VARS


@contextmanager
def controlled_env(present, monkeypatch):
    """Set exactly ``present`` (a mapping) and clear all other controlled vars.

    ``load_dotenv`` is patched to a no-op so a real ``.env`` file cannot
    repopulate the environment and make the test non-deterministic.
    """
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    for var in ALL_CONTROLLED_VARS:
        monkeypatch.delenv(var, raising=False)
    for var, value in present.items():
        monkeypatch.setenv(var, value)
    yield


# --- Property-based test (Property 4) ---------------------------------------


@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    removed=st.sets(st.sampled_from(REQUIRED_ENV_VARS), min_size=1),
)
def test_missing_required_var_raises_naming_a_missing_var(removed, monkeypatch):
    """For any non-empty subset of required vars removed, ``load()`` raises a
    ValueError whose message names at least one of the missing variables.

    **Validates: Requirements 2.2**
    """
    # Build an environment where every required+optional var is present
    # except those in ``removed``.
    present = {var: f"value-for-{var}" for var in ALL_CONTROLLED_VARS if var not in removed}

    with controlled_env(present, monkeypatch):
        with pytest.raises(ValueError) as exc_info:
            config.load()

    message = str(exc_info.value)
    assert any(var in message for var in removed), (
        f"Error message {message!r} did not name any of the removed required "
        f"variables {sorted(removed)}"
    )


@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    removed=st.sets(st.sampled_from(REQUIRED_ENV_VARS), min_size=1),
    empty_instead_of_unset=st.booleans(),
)
def test_load_never_silently_returns_defaults_for_required_keys(
    removed, empty_instead_of_unset, monkeypatch
):
    """``load()`` must never silently succeed when a required key is missing or
    empty — it must raise rather than substitute a default/blank value.

    **Validates: Requirements 2.2**
    """
    present = {var: f"value-for-{var}" for var in ALL_CONTROLLED_VARS if var not in removed}

    with controlled_env(present, monkeypatch):
        if empty_instead_of_unset:
            # An empty string is also an invalid required value.
            for var in removed:
                monkeypatch.setenv(var, "")
        with pytest.raises(ValueError):
            config.load()


# --- Unit tests: explicit examples and the happy path -----------------------


@pytest.mark.parametrize("missing_var", list(REQUIRED_ENV_VARS))
def test_each_required_var_named_when_only_it_is_missing(missing_var, monkeypatch):
    """Removing a single required var raises a ValueError naming that var."""
    present = {var: f"value-for-{var}" for var in ALL_CONTROLLED_VARS if var != missing_var}

    with controlled_env(present, monkeypatch):
        with pytest.raises(ValueError) as exc_info:
            config.load()

    assert missing_var in str(exc_info.value)


def test_load_succeeds_when_all_required_present(monkeypatch):
    """With all required vars set, ``load()`` returns populated Settings."""
    present = {var: f"value-for-{var}" for var in REQUIRED_ENV_VARS}

    with controlled_env(present, monkeypatch):
        settings_obj = config.load()

    assert settings_obj.dd_api_key == "value-for-DD_API_KEY"
    assert settings_obj.dd_llmobs_ml_app == "value-for-DD_LLMOBS_ML_APP"
    # Defaults applied for the optional vars.
    assert settings_obj.aws_region == config.DEFAULT_AWS_REGION
    assert settings_obj.dd_site == config.DEFAULT_DD_SITE
    # Constants.
    assert settings_obj.model_id == config.MODEL_ID
    assert settings_obj.model_name == config.MODEL_NAME
    assert settings_obj.model_provider == config.MODEL_PROVIDER


def test_empty_required_var_treated_as_missing(monkeypatch):
    """An empty-string required var fails fast just like an unset one."""
    present = {var: f"value-for-{var}" for var in REQUIRED_ENV_VARS}
    present["DD_API_KEY"] = ""

    with controlled_env(present, monkeypatch):
        with pytest.raises(ValueError) as exc_info:
            config.load()

    assert "DD_API_KEY" in str(exc_info.value)
