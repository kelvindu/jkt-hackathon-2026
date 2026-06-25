"""Operational tools the agent can call during an investigation.

Unlike the reference (which read a static ``dummy_app`` and opened a GitHub PR),
these tools act against the **live** ``auth-service`` running alongside the agent
in the cluster — so the demo shows a genuine reason→act→remediate loop:

    1. query_service_health      — is auth-service actually unhealthy?
    2. query_datadog_metrics     — what does the error/latency signal look like?
    3. read_application_code     — which code path causes it (the chaos bug)?
    4. remediate_disable_chaos   — auto-remediation: turn the incident off

Each function is decorated with ``@tool`` so it emits a tool span nested in the
investigation workflow (DD #3 Tool Visible), and is also exposed to Bedrock via
:data:`TOOL_CONFIG`. ``execute_tool`` is the dispatcher used by the agent loop.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import requests

from . import observability as obs

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 8


# --------------------------------------------------------------------------
# Bedrock tool schema
# --------------------------------------------------------------------------

TOOL_CONFIG: dict[str, Any] = {
    "tools": [
        {
            "toolSpec": {
                "name": "query_service_health",
                "description": (
                    "Check the live health of a Spring Boot service via its "
                    "/actuator/health endpoint. Use this first to confirm the alerting "
                    "service is actually degraded and inspect component status (db, pool)."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "service": {
                                "type": "string",
                                "description": "Service name, e.g. 'auth-service'.",
                            }
                        },
                        "required": ["service"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "query_datadog_metrics",
                "description": (
                    "Run a Datadog metrics query (v1 /query API) over the last 15 minutes "
                    "to quantify error rate or latency. Example queries: "
                    "'sum:trace.servlet.request.errors{service:auth-service}.as_count()' or "
                    "'avg:trace.servlet.request.duration{service:auth-service}'."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Datadog metrics query string."}
                        },
                        "required": ["query"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "read_application_code",
                "description": (
                    "Read source from the application repo to find the code-level root "
                    "cause (e.g. blocking sleep, missing timeout, connection-pool exhaustion). "
                    "Path is relative to the app root, e.g. "
                    "'src/main/java/com/hackathon/auth/service/AuthValidationService.java'."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "filepath": {"type": "string", "description": "Path relative to the app root."}
                        },
                        "required": ["filepath"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "remediate_disable_chaos",
                "description": (
                    "REMEDIATION: disable the fault injection on auth-service by calling its "
                    "chaos/deactivate admin endpoint. Call this only after you have confirmed "
                    "the root cause is the injected chaos fault. Returns the remediation result."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "service": {
                                "type": "string",
                                "description": "Service to remediate, e.g. 'auth-service'.",
                            }
                        },
                        "required": ["service"],
                    }
                },
            }
        },
    ]
}

TOOL_NAMES = frozenset(
    {"query_service_health", "query_datadog_metrics", "read_application_code", "remediate_disable_chaos"}
)


# --------------------------------------------------------------------------
# Tool implementations (each emits a @tool span)
# --------------------------------------------------------------------------


@obs.tool(name="query_service_health")
def query_service_health(service: str) -> dict[str, Any]:
    """GET ``{AUTH_SERVICE_URL}/actuator/health`` and summarize component status."""
    base = _service_base_url(service)
    url = f"{base}/actuator/health"
    obs.annotate(input_data={"service": service, "url": url})
    try:
        resp = requests.get(url, timeout=_HTTP_TIMEOUT)
        result: dict[str, Any] = {
            "service": service,
            "http_status": resp.status_code,
            "healthy": resp.status_code == 200,
        }
        try:
            result["details"] = resp.json()
        except ValueError:
            result["details"] = resp.text[:500]
        obs.annotate(output_data=result)
        return {"success": True, "result": result}
    except requests.RequestException as exc:
        # An unreachable/timing-out service IS the signal — return it as data.
        result = {"service": service, "healthy": False, "error": str(exc)}
        obs.annotate(output_data=result)
        return {"success": True, "result": result}


@obs.tool(name="query_datadog_metrics")
def query_datadog_metrics(query: str) -> dict[str, Any]:
    """Query Datadog metrics over the last 15 minutes (best-effort)."""
    import time

    obs.annotate(input_data={"query": query})
    api_key = os.getenv("DD_API_KEY", "")
    app_key = os.getenv("DD_APP_KEY", "")
    if not api_key or not app_key:
        return {
            "success": True,
            "result": {
                "query": query,
                "note": "DD_APP_KEY not configured; metrics enrichment skipped.",
                "series": [],
            },
        }
    site = os.getenv("DD_SITE", "datadoghq.com")
    now = int(time.time())
    try:
        resp = requests.get(
            f"https://api.{site}/api/v1/query",
            params={"from": now - 900, "to": now, "query": query},
            headers={"DD-API-KEY": api_key, "DD-APPLICATION-KEY": app_key},
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            return {"success": False, "error": f"Datadog query HTTP {resp.status_code}: {resp.text[:200]}"}
        series = resp.json().get("series", [])
        summary = [
            {
                "metric": s.get("metric"),
                "points": len(s.get("pointlist", [])),
                "latest": (s.get("pointlist") or [[None, None]])[-1][1],
            }
            for s in series
        ]
        result = {"query": query, "series_count": len(series), "summary": summary}
        obs.annotate(output_data=result)
        return {"success": True, "result": result}
    except requests.RequestException as exc:
        return {"success": False, "error": f"Datadog query failed: {exc}"}


@obs.tool(name="read_application_code")
def read_application_code(filepath: str) -> dict[str, Any]:
    """Read a file from ``APP_SOURCE_DIR`` with a path-traversal guard."""
    obs.annotate(input_data={"filepath": filepath})
    base = Path(os.getenv("APP_SOURCE_DIR", "./app_under_test")).resolve()
    target = (base / filepath).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return {"success": False, "error": f"path traversal rejected: {filepath!r}"}
    if not target.is_file():
        return {"success": False, "error": f"file not found under app root: {filepath!r}"}
    try:
        content = target.read_text(encoding="utf-8")
        obs.annotate(output_data={"chars": len(content)})
        return {"success": True, "result": content[:8000]}
    except OSError as exc:
        return {"success": False, "error": f"could not read {filepath!r}: {exc}"}


@obs.tool(name="remediate_disable_chaos")
def remediate_disable_chaos(service: str = "auth-service") -> dict[str, Any]:
    """POST ``/api/v1/admin/chaos/deactivate`` to stop the injected fault."""
    base = _service_base_url(service)
    url = f"{base}/api/v1/admin/chaos/deactivate"
    obs.annotate(input_data={"service": service, "url": url})
    if not _env_bool("AUTO_REMEDIATE", True):
        result = {"service": service, "remediated": False, "note": "AUTO_REMEDIATE disabled"}
        obs.annotate(output_data=result)
        return {"success": True, "result": result}
    try:
        resp = requests.post(url, timeout=_HTTP_TIMEOUT)
        result = {
            "service": service,
            "remediated": resp.status_code == 200,
            "http_status": resp.status_code,
            "action": "chaos mode deactivated",
        }
        obs.annotate(output_data=result)
        return {"success": True, "result": result}
    except requests.RequestException as exc:
        return {"success": False, "error": f"remediation call failed: {exc}"}


# --------------------------------------------------------------------------
# Dispatcher
# --------------------------------------------------------------------------


def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Route a tool-use request to its implementation. Returns {success, result|error}."""
    try:
        if name == "query_service_health":
            return query_service_health(arguments.get("service", "auth-service"))
        if name == "query_datadog_metrics":
            return query_datadog_metrics(arguments.get("query", ""))
        if name == "read_application_code":
            return read_application_code(arguments.get("filepath", ""))
        if name == "remediate_disable_chaos":
            return remediate_disable_chaos(arguments.get("service", "auth-service"))
        return {"success": False, "error": f"unknown tool: {name!r}"}
    except Exception as exc:  # noqa: BLE001 - tool faults are recoverable
        logger.warning("tool %s raised: %s", name, exc)
        return {"success": False, "error": str(exc)}


def _service_base_url(service: str) -> str:
    """Resolve a service base URL. auth-service uses AUTH_SERVICE_URL; others by DNS."""
    if service in ("auth-service", "", None):
        return (os.getenv("AUTH_SERVICE_URL", "http://auth-service:8080")).rstrip("/")
    # In-cluster DNS convention: <service>:8080
    return f"http://{service}:8080"


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
