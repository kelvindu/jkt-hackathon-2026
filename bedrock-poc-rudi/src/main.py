"""
CLI entry point for the Autonomous Incident Response Agent.

Usage:
    python -m src.main <alert_config_path> [--scenario-index N]

Requirements: 4.3, 6.3, 9.2
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from .agent import InvestigationAgent
from .bedrock_client import BedrockClient
from .config import ConfigLoader
from .events import DatadogEventsPublisher
from .mcp_client import MCPClient
from .observability import DDTraceWrapper

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Configure root logger with JSON-friendly format and env-controlled level."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        level=level,
        stream=sys.stdout,
    )


def _validate_environment() -> dict:
    """
    Validate required environment variables and return parsed config.

    Exits with code 1 if any required variable is missing.

    Returns:
        Dictionary of resolved configuration values
    """
    required = {
        "AWS_ACCESS_KEY_ID": os.getenv("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": os.getenv("AWS_SECRET_ACCESS_KEY"),
        "DD_API_KEY": os.getenv("DD_API_KEY"),
    }

    missing = [k for k, v in required.items() if not v]
    if missing:
        for var in missing:
            logger.error(
                json.dumps(
                    {
                        "event": "startup.missing_env",
                        "variable": var,
                        "message": f"Required environment variable '{var}' is not set",
                    }
                )
            )
        sys.exit(1)

    raw_mcp_cmd = os.getenv(
        "MCP_SERVER_COMMAND", '["npx", "-y", "@datadog/mcp-server-datadog"]'
    )
    try:
        mcp_command = json.loads(raw_mcp_cmd)
        if not isinstance(mcp_command, list):
            raise ValueError("MCP_SERVER_COMMAND must be a JSON array")
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error(
            json.dumps(
                {
                    "event": "startup.invalid_env",
                    "variable": "MCP_SERVER_COMMAND",
                    "message": str(exc),
                }
            )
        )
        sys.exit(1)

    raw_max_iter = os.getenv("MAX_ITERATIONS", "10")
    try:
        max_iterations = int(raw_max_iter)
        if max_iterations < 1:
            raise ValueError("MAX_ITERATIONS must be >= 1")
    except ValueError as exc:
        logger.error(
            json.dumps(
                {
                    "event": "startup.invalid_env",
                    "variable": "MAX_ITERATIONS",
                    "message": str(exc),
                }
            )
        )
        sys.exit(1)

    return {
        "aws_region": os.getenv("AWS_REGION", "us-east-1"),
        "dd_api_key": os.getenv("DD_API_KEY"),
        "dd_site": os.getenv("DD_SITE", "datadoghq.com"),
        "mcp_server_command": mcp_command,
        "max_iterations": max_iterations,
    }


def _load_dotenv() -> None:
    """Load .env file if python-dotenv is available (optional dependency)."""
    try:
        from dotenv import load_dotenv  # type: ignore[import]

        load_dotenv()
    except ImportError:
        pass


def main() -> None:
    _load_dotenv()
    _configure_logging()

    parser = argparse.ArgumentParser(
        description="Autonomous Incident Response Agent — investigates alerts using Bedrock + Datadog MCP"
    )
    parser.add_argument(
        "alert_config",
        metavar="ALERT_CONFIG",
        help="Path to alert configuration file (JSON or YAML)",
    )
    parser.add_argument(
        "--scenario-index",
        type=int,
        default=0,
        metavar="N",
        help="Zero-based index of the scenario to investigate (default: 0)",
    )
    args = parser.parse_args()

    env = _validate_environment()

    # Load alert scenario
    scenarios = ConfigLoader.load_scenarios(args.alert_config)
    if args.scenario_index >= len(scenarios):
        logger.error(
            json.dumps(
                {
                    "event": "startup.invalid_scenario_index",
                    "index": args.scenario_index,
                    "available": len(scenarios),
                }
            )
        )
        sys.exit(1)

    scenario = scenarios[args.scenario_index]
    scenario_id = scenario.name.lower().replace(" ", "-")

    logger.info(
        json.dumps(
            {
                "event": "startup.scenario_selected",
                "scenario_id": scenario_id,
                "alert_name": scenario.name,
            }
        )
    )

    # Initialize components
    bedrock_client = BedrockClient(
        model_id=os.getenv("BEDROCK_MODEL_ID", "amazon.nova-micro-v1:0")
    )
    mcp_client = MCPClient(env["mcp_server_command"])
    observability = DDTraceWrapper()
    events_publisher = DatadogEventsPublisher(
        api_key=env["dd_api_key"],
        site=env["dd_site"],
    )

    # Connect MCP server
    try:
        mcp_client.connect()
    except Exception as exc:
        logger.error(
            json.dumps(
                {
                    "event": "startup.mcp_connection_failed",
                    "error": str(exc),
                }
            )
        )
        sys.exit(1)

    try:
        agent = InvestigationAgent(
            bedrock_client=bedrock_client,
            mcp_client=mcp_client,
            max_iterations=env["max_iterations"],
            observability=observability,
        )

        report = agent.investigate(scenario)

        # Publish RCA to Datadog Events
        published = events_publisher.publish_rca(report, scenario_id)
        if not published:
            logger.warning(
                json.dumps(
                    {
                        "event": "events.publish_skipped",
                        "scenario_id": scenario_id,
                    }
                )
            )

        # Emit summary to stdout
        output: dict[str, Any] = {
            "alert_name": report.alert_name,
            "investigation_summary": report.investigation_summary,
            "key_findings": report.key_findings,
            "iterations_used": report.iterations_used,
            "timestamp": report.timestamp,
            "events_published": published,
        }
        if report.blast_radius is not None:
            output["blast_radius"] = report.blast_radius.to_dict()

        print(json.dumps(output, indent=2))

    finally:
        mcp_client.disconnect()


if __name__ == "__main__":
    main()
