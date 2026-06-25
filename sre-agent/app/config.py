"""Configuration loading and fail-fast validation for the SRE agent.

Loads environment variables (``.env`` via python-dotenv plus the process
environment) into a validated :class:`Settings` object. Validation is eager so
a missing credential is reported by name *before* any network call is made.

Aligned with the hackathon checklist env contract (see ``.env.template``):
``DD_API_KEY``, ``DD_LLMOBS_ML_APP``, ``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Model constants — Nova Pro slice of the hackathon (AWS task #1, Jakarta #7)
# --------------------------------------------------------------------------
MODEL_ID = "amazon.nova-pro-v1:0"
MODEL_NAME = "nova-pro"
MODEL_PROVIDER = "bedrock"

# Nova Pro on-demand pricing (USD per 1K tokens) — used for cost tracking.
# Source: AWS Bedrock pricing for amazon.nova-pro-v1:0.
NOVA_PRO_INPUT_USD_PER_1K = 0.0008
NOVA_PRO_OUTPUT_USD_PER_1K = 0.0032

DEFAULT_AWS_REGION = "us-east-1"
DEFAULT_DD_SITE = "datadoghq.com"
DEFAULT_ML_APP = "sre-incident-agent"
DEFAULT_SERVICE = "sre-incident-agent"
DEFAULT_AUTH_SERVICE_URL = "http://auth-service:8080"
DEFAULT_MAX_ITERATIONS = 8

# Required only for the agent to actually call Bedrock + emit spans. The webhook
# guardrail surface degrades gracefully without them (still sanitizes payloads).
REQUIRED_ENV_VARS = (
    "DD_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)


@dataclass
class Settings:
    """Validated runtime configuration."""

    # Datadog
    dd_api_key: str
    dd_app_key: str
    dd_site: str
    dd_llmobs_ml_app: str
    dd_service: str
    dd_env: str

    # AWS Bedrock
    aws_region: str
    model_id: str
    model_name: str
    model_provider: str
    guardrail_id: str
    guardrail_version: str

    # Agent behaviour
    max_iterations: int
    auth_service_url: str
    app_source_dir: str
    auto_remediate: bool

    # Notification sinks
    google_chat_webhook_url: str

    @property
    def has_aws(self) -> bool:
        return bool(os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"))

    @property
    def has_datadog(self) -> bool:
        return bool(self.dd_api_key)


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]

        load_dotenv()
    except ImportError:
        pass


def load(*, require: bool = True) -> Settings:
    """Load and validate settings from the environment.

    Args:
        require: When True, raise if any value in ``REQUIRED_ENV_VARS`` is
            missing. The webhook server passes ``require=False`` so it can boot
            and still sanitize payloads even before credentials are wired in.

    Raises:
        ValueError: If ``require`` and a required variable is unset/empty.
    """
    _load_dotenv()

    if require:
        missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
        if missing:
            raise ValueError(
                "Missing required environment variable(s): "
                + ", ".join(missing)
                + ". Set them in your .env file or environment and re-run."
            )

    return Settings(
        dd_api_key=os.environ.get("DD_API_KEY", ""),
        dd_app_key=os.environ.get("DD_APP_KEY", ""),
        dd_site=os.environ.get("DD_SITE") or DEFAULT_DD_SITE,
        dd_llmobs_ml_app=os.environ.get("DD_LLMOBS_ML_APP") or DEFAULT_ML_APP,
        dd_service=os.environ.get("DD_SERVICE") or DEFAULT_SERVICE,
        dd_env=os.environ.get("DD_ENV") or "hackathon",
        aws_region=os.environ.get("AWS_REGION") or DEFAULT_AWS_REGION,
        model_id=os.environ.get("BEDROCK_MODEL_ID") or MODEL_ID,
        model_name=MODEL_NAME,
        model_provider=MODEL_PROVIDER,
        guardrail_id=os.environ.get("BEDROCK_GUARDRAIL_ID", ""),
        guardrail_version=os.environ.get("BEDROCK_GUARDRAIL_VERSION", "DRAFT"),
        max_iterations=_env_int("MAX_ITERATIONS", DEFAULT_MAX_ITERATIONS),
        auth_service_url=(os.environ.get("AUTH_SERVICE_URL") or DEFAULT_AUTH_SERVICE_URL).rstrip("/"),
        app_source_dir=os.environ.get("APP_SOURCE_DIR", "./app_under_test"),
        auto_remediate=_env_bool("AUTO_REMEDIATE", True),
        google_chat_webhook_url=os.environ.get("GOOGLE_CHAT_WEBHOOK_URL", ""),
    )


def estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Estimate Nova Pro invocation cost in USD from token counts."""
    cost = (
        (input_tokens / 1000.0) * NOVA_PRO_INPUT_USD_PER_1K
        + (output_tokens / 1000.0) * NOVA_PRO_OUTPUT_USD_PER_1K
    )
    return round(cost, 6)


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if not raw:
        return default
    try:
        value = int(raw)
        return value if value >= 1 else default
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
