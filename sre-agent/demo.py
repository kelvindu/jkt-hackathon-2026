#!/usr/bin/env python3
"""One-command live demo for the Autonomous SRE Incident-Response Agent.

Runs the canonical auth-service incident (DB connection-pool timeout under chaos)
against alerts/auth_service_timeout.json, using the live tools to investigate and
auto-remediate. Mirrors bedrock-poc-rudi/demo.py.

Usage:
    python demo.py

Requires a .env with AWS credentials + DD_API_KEY (see .env.example). For the
auto-remediation step to do real work, point AUTH_SERVICE_URL at a running
auth-service (default http://localhost:8080); otherwise the agent still completes
the investigation and reports the remediation call outcome.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_ALERT = _ROOT / "alerts" / "auth_service_timeout.json"

if __name__ == "__main__":
    from app.main import main

    sys.exit(main([str(_ALERT)]))
