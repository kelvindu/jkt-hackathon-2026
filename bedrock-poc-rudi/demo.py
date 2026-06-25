#!/usr/bin/env python3
"""
One-command live demo for the Autonomous Incident Response Agent.

Runs the canonical checkout incident (inc_43 + inc_13) against
alerts/demo_live.json and dummy_app/services/orders.py.

Usage:
    python demo.py

Requires .env with AWS credentials, DD_API_KEY, GITHUB_TOKEN, GITHUB_REPO.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_ALERT = _ROOT / "alerts" / "demo_live.json"

if __name__ == "__main__":
    sys.argv = ["demo", str(_ALERT)]
    from src.main import main

    main()
