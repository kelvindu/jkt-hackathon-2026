"""FastAPI webhook server — the EKS-deployed face of the SRE agent.

Endpoints
---------
GET  /healthz   — liveness/readiness probe (k8s).
GET  /          — service banner + config summary.
POST /webhook   — receive a Datadog monitor alert (or an attack payload from
                  ops-simulator), GUARDRAIL-SANITIZE it, then run the autonomous
                  investigation. Always returns the sanitized payload + redaction
                  report so SecurityAttackSimulator detects ``[REDACTED_*]`` /
                  ``sanitized`` (AWS #6 Guardrails On).
POST /invoke    — run an investigation from an explicit scenario body (demo/manual).

Investigations run in a background task so the webhook responds immediately — the
caller (ops-simulator) only needs the sanitization verdict synchronously.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse

from . import __version__
from . import observability as obs
from .config import load
from .guardrails import sanitize_payload
from .runner import run_investigation
from .scenarios import AlertScenario, from_webhook

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("sre-agent.server")

# require=False so the pod boots and still sanitizes even before creds are wired.
settings = load(require=False)
obs.enable(settings)

app = FastAPI(title="SRE Incident-Response Agent", version=__version__)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "ok", "version": __version__}


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": "sre-incident-agent",
        "version": __version__,
        "model": settings.model_id,
        "ml_app": settings.dd_llmobs_ml_app,
        "observability": obs.is_enabled(),
        "aws_configured": settings.has_aws,
        "guardrail": bool(settings.guardrail_id) or "input-sanitizer",
        "endpoints": ["/healthz", "/webhook", "/invoke"],
    }


@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks) -> JSONResponse:
    """Sanitize an inbound alert, then investigate it asynchronously."""
    payload = await _read_json(request)

    # --- Guardrail layer (synchronous, always-on) ---
    result = sanitize_payload(payload)
    report = result.to_dict()
    logger.info(
        '{"event":"webhook.received","sanitized":%s,"redactions":%d,"injections":%d}'
        % (str(report["sanitized"]).lower(), report["total_redactions"], report["injection_attempts_blocked"])
    )

    response_body: dict[str, Any] = {
        "status": "accepted",
        "sanitized": report["sanitized"],
        "guardrail_report": report,
        "sanitized_payload": result.sanitized_payload,
    }

    # Only launch an investigation for genuine alerts, not pure attack probes.
    if settings.has_aws and not _looks_like_attack_only(result):
        scenario = from_webhook(result.sanitized_payload)
        background.add_task(_investigate_safely, scenario)
        response_body["investigation"] = "started"
    else:
        response_body["investigation"] = "skipped"

    return JSONResponse(status_code=200, content=response_body)


@app.post("/invoke")
async def invoke(request: Request) -> JSONResponse:
    """Run an investigation synchronously from an explicit scenario body."""
    body = await _read_json(request)
    if not settings.has_aws:
        return JSONResponse(status_code=503, content={"error": "AWS credentials not configured"})
    scenario = AlertScenario(
        name=body.get("name", "Manual Alert"),
        description=body.get("description", ""),
        initial_context=body.get("initial_context", {}),
        metadata=body.get("metadata", {}),
    )
    report, published = run_investigation(scenario, settings)
    return JSONResponse(status_code=200, content={**report.to_dict(), "events_published": published})


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _investigate_safely(scenario: AlertScenario) -> None:
    try:
        report, published = run_investigation(scenario, settings)
        logger.info(
            '{"event":"webhook.investigation_done","alert":%r,"remediated":%s,"published":%s}'
            % (scenario.name, str(report.remediated).lower(), str(published).lower())
        )
    except Exception as exc:  # noqa: BLE001 - background task must never crash the server
        logger.error('{"event":"webhook.investigation_error","error":%r}' % str(exc))


def _looks_like_attack_only(result: Any) -> bool:
    """Heuristic: a payload that is mostly injection/redaction is a security probe."""
    return result.injection_attempts >= 1 and result.total_redactions >= 3


async def _read_json(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {"body": str(data)}
    except Exception:  # noqa: BLE001 - tolerate malformed bodies from attackers
        raw = (await request.body()).decode("utf-8", errors="replace")
        return {"body": raw}
