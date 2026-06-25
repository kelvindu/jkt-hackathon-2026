"""CLI entry point for a one-shot investigation (demo / local).

Usage:
    python -m app.main alerts/auth_service_timeout.json [--scenario-index N]

Prints the blast-radius card, runs the investigation (full LLMObs trace), and
emits the RCA as JSON to stdout. Mirrors what the webhook server does per alert.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import load
from .runner import run_investigation
from .scenarios import load_scenarios


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    parser = argparse.ArgumentParser(description="Autonomous SRE incident-response agent (Bedrock Nova Pro + Datadog).")
    parser.add_argument("alert_config", help="Path to alert scenario JSON file.")
    parser.add_argument("--scenario-index", type=int, default=0, help="Zero-based scenario index.")
    args = parser.parse_args(argv)

    try:
        settings = load(require=True)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    scenarios = load_scenarios(args.alert_config)
    if args.scenario_index >= len(scenarios):
        print(f"error: scenario index {args.scenario_index} out of range (have {len(scenarios)})", file=sys.stderr)
        return 1
    scenario = scenarios[args.scenario_index]

    report, published = run_investigation(scenario, settings)

    output = {**report.to_dict(), "events_published": published}
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
