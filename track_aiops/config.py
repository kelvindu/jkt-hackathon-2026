"""Configuration loading and fail-fast validation for ``track_aiops``.

This module loads environment variables (from a ``.env`` file via
``python-dotenv`` and the process environment) into a validated
:class:`Settings` dataclass. Validation happens eagerly in :func:`load` so
that a missing credential is reported by name *before* any network call is
made.

Requirements: 2.1, 2.2, 2.3, 2.4
"""

from dataclasses import dataclass

from dotenv import load_dotenv

import os

# Model constants — fixed for the Nova Pro slice of the hackathon.
MODEL_ID = "amazon.nova-pro-v1:0"
MODEL_NAME = "nova-pro"
MODEL_PROVIDER = "bedrock"

# Defaults applied when the corresponding optional env var is absent.
DEFAULT_AWS_REGION = "us-east-1"
DEFAULT_DD_SITE = "datadoghq.com"

# Required environment variables — missing/empty values fail fast in load().
REQUIRED_ENV_VARS = (
    "DD_API_KEY",
    "DD_LLMOBS_ML_APP",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)


@dataclass
class Settings:
    """Validated configuration for invoking Bedrock and emitting DD spans.

    Attributes:
        dd_api_key: Datadog API key (required).
        dd_site: Datadog site, e.g. ``datadoghq.com`` (default applied).
        dd_llmobs_ml_app: LLM Observability ml_app / team name (required).
        aws_region: AWS region for the Bedrock runtime (default applied).
        model_id: Bedrock model id — constant ``amazon.nova-pro-v1:0``.
        model_name: Span model name — constant ``nova-pro``.
        model_provider: Span model provider — constant ``bedrock``.
    """

    dd_api_key: str
    dd_site: str
    dd_llmobs_ml_app: str
    aws_region: str
    model_id: str
    model_name: str
    model_provider: str


def load() -> Settings:
    """Load and validate settings from the environment.

    Reads a ``.env`` file (if present) into the environment, validates that
    every required credential is set and non-empty, applies defaults for the
    optional variables, and returns a populated :class:`Settings`.

    Returns:
        A fully populated :class:`Settings` instance.

    Raises:
        ValueError: If any required environment variable
            (``DD_API_KEY``, ``DD_LLMOBS_ML_APP``, ``AWS_ACCESS_KEY_ID``,
            ``AWS_SECRET_ACCESS_KEY``) is unset or empty. The message names
            the exact missing variable.
    """
    load_dotenv()

    for var in REQUIRED_ENV_VARS:
        value = os.environ.get(var)
        if not value:
            raise ValueError(
                f"Missing required environment variable: {var}. "
                "Set it in your .env file or environment and re-run."
            )

    return Settings(
        dd_api_key=os.environ["DD_API_KEY"],
        dd_site=os.environ.get("DD_SITE") or DEFAULT_DD_SITE,
        dd_llmobs_ml_app=os.environ["DD_LLMOBS_ML_APP"],
        aws_region=os.environ.get("AWS_REGION") or DEFAULT_AWS_REGION,
        model_id=MODEL_ID,
        model_name=MODEL_NAME,
        model_provider=MODEL_PROVIDER,
    )
