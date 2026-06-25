#!/usr/bin/env python3
"""
Investigation Insights Dashboard

Queries Datadog API to show operational metrics and insights about
autonomous incident response investigations.

Usage:
    python scripts/show_insights.py [--hours HOURS] [--format FORMAT]

Requirements:
    - DD_API_KEY environment variable
    - DD_APP_KEY environment variable (Datadog Application Key)
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import requests


class DatadogInsightsClient:
    """Client for querying Datadog API for investigation insights."""
    
    def __init__(self, api_key: str, app_key: str, site: str = "datadoghq.com"):
        self.api_key = api_key
        self.app_key = app_key
        self.site = site
        self.base_url = f"https://api.{site}"
        
    def _headers(self) -> Dict[str, str]:
        return {
            "DD-API-KEY": self.api_key,
            "DD-APPLICATION-KEY": self.app_key,
            "Content-Type": "application/json",
        }
    
    def query_investigation_traces(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Query investigation traces from the last N hours.
        
        Uses the APM Trace Search API to find all spans for the
        incident-response-agent service.
        """
        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours)
        
        # Convert to epoch milliseconds
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)
        
        # Query parameters
        params = {
            "start": start_ms,
            "end": end_ms,
            "filter[query]": "service:incident-response-agent",
        }
        
        try:
            response = requests.get(
                f"{self.base_url}/api/v2/spans/events",
                headers=self._headers(),
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            return response.json().get("data", [])
        except requests.RequestException as e:
            print(f"Error querying Datadog API: {e}", file=sys.stderr)
            return []
    
    def query_metrics(self, metric_query: str, hours: int = 24) -> Dict[str, Any]:
        """Query time-series metrics from Datadog."""
        end_time = int(datetime.now(timezone.utc).timestamp())
        start_time = end_time - (hours * 3600)
        
        params = {
            "query": metric_query,
            "from": start_time,
            "to": end_time,
        }
        
        try:
            response = requests.get(
                f"{self.base_url}/api/v1/query",
                headers=self._headers(),
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error querying metrics: {e}", file=sys.stderr)
            return {}


class InvestigationInsights:
    """Analyzes investigation traces to extract insights."""
    
    def __init__(self, traces: List[Dict[str, Any]]):
        self.traces = traces
        self.workflow_spans = self._filter_workflows()
        self.llm_spans = self._filter_llm_calls()
        self.tool_spans = self._filter_tool_calls()
    
    def _filter_workflows(self) -> List[Dict[str, Any]]:
        """Extract workflow-level spans."""
        return [
            t for t in self.traces
            if t.get("attributes", {}).get("resource.name") == "incident_investigation"
        ]
    
    def _filter_llm_calls(self) -> List[Dict[str, Any]]:
        """Extract LLM call spans."""
        return [
            t for t in self.traces
            if t.get("attributes", {}).get("operation.name") == "bedrock.converse"
        ]
    
    def _filter_tool_calls(self) -> List[Dict[str, Any]]:
        """Extract tool call spans."""
        return [
            t for t in self.traces
            if t.get("attributes", {}).get("span.kind") == "tool"
        ]
    
    def get_investigation_count(self) -> int:
        """Total number of investigations."""
        return len(self.workflow_spans)
    
    def get_avg_duration(self) -> float:
        """Average investigation duration in seconds."""
        if not self.workflow_spans:
            return 0.0
        
        durations = []
        for span in self.workflow_spans:
            # Duration is in nanoseconds
            duration_ns = span.get("attributes", {}).get("duration", 0)
            durations.append(duration_ns / 1_000_000_000)
        
        return sum(durations) / len(durations) if durations else 0.0
    
    def get_success_rate(self) -> float:
        """Percentage of investigations that completed successfully."""
        if not self.workflow_spans:
            return 0.0
        
        successful = sum(
            1 for span in self.workflow_spans
            if not span.get("attributes", {}).get("error", False)
        )
        
        return (successful / len(self.workflow_spans)) * 100
    
    def get_tool_usage_stats(self) -> Dict[str, int]:
        """Count tool usage by tool name."""
        tool_names = [
            span.get("attributes", {}).get("resource.name", "unknown")
            for span in self.tool_spans
        ]
        return dict(Counter(tool_names).most_common())
    
    def get_avg_iterations(self) -> float:
        """Average number of LLM iterations per investigation."""
        if not self.workflow_spans:
            return 0.0
        
        # Count LLM calls per workflow
        workflow_ids = {
            span.get("id"): 0
            for span in self.workflow_spans
        }
        
        for llm_span in self.llm_spans:
            parent_id = llm_span.get("relationships", {}).get("parent", {}).get("data", {}).get("id")
            if parent_id in workflow_ids:
                workflow_ids[parent_id] += 1
        
        iterations = list(workflow_ids.values())
        return sum(iterations) / len(iterations) if iterations else 0.0
    
    def get_token_usage(self) -> Dict[str, int]:
        """Total token usage across all investigations."""
        total_input = 0
        total_output = 0
        
        for span in self.llm_spans:
            attrs = span.get("attributes", {})
            total_input += attrs.get("bedrock.input_tokens", 0)
            total_output += attrs.get("bedrock.output_tokens", 0)
        
        return {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "total_tokens": total_input + total_output,
        }
    
    def get_quality_metrics(self) -> Dict[str, Any]:
        """Extract RCA quality metrics from evaluations."""
        quality_scores = []
        
        for span in self.workflow_spans:
            attrs = span.get("attributes", {})
            score = attrs.get("quality_score")
            if score is not None:
                quality_scores.append(score)
        
        if not quality_scores:
            return {"available": False}
        
        return {
            "available": True,
            "avg_score": sum(quality_scores) / len(quality_scores),
            "min_score": min(quality_scores),
            "max_score": max(quality_scores),
            "count": len(quality_scores),
        }


def format_text_output(insights: InvestigationInsights, hours: int) -> str:
    """Format insights as human-readable text."""
    output = []
    output.append("=" * 70)
    output.append("🔍 AUTONOMOUS INCIDENT RESPONSE - INVESTIGATION INSIGHTS")
    output.append("=" * 70)
    output.append(f"Time Range: Last {hours} hours")
    output.append("")
    
    # Overview
    output.append("📊 OVERVIEW")
    output.append("-" * 70)
    output.append(f"Total Investigations:      {insights.get_investigation_count()}")
    output.append(f"Average Duration:          {insights.get_avg_duration():.1f}s")
    output.append(f"Success Rate:              {insights.get_success_rate():.1f}%")
    output.append(f"Avg Iterations per RCA:    {insights.get_avg_iterations():.1f}")
    output.append("")
    
    # Token Usage
    tokens = insights.get_token_usage()
    output.append("💰 TOKEN USAGE & COST")
    output.append("-" * 70)
    output.append(f"Total Input Tokens:        {tokens['input_tokens']:,}")
    output.append(f"Total Output Tokens:       {tokens['output_tokens']:,}")
    output.append(f"Total Tokens:              {tokens['total_tokens']:,}")
    
    # Estimated cost (Amazon Nova Micro rates)
    input_cost = tokens['input_tokens'] / 1000 * 0.000035
    output_cost = tokens['output_tokens'] / 1000 * 0.00014
    total_cost = input_cost + output_cost
    output.append(f"Estimated Cost:            ${total_cost:.4f}")
    
    if insights.get_investigation_count() > 0:
        avg_cost = total_cost / insights.get_investigation_count()
        output.append(f"Avg Cost per Investigation: ${avg_cost:.4f}")
    output.append("")
    
    # Tool Usage
    tool_stats = insights.get_tool_usage_stats()
    if tool_stats:
        output.append("🔧 TOOL USAGE")
        output.append("-" * 70)
        total_tools = sum(tool_stats.values())
        for i, (tool, count) in enumerate(tool_stats.items(), 1):
            pct = (count / total_tools) * 100 if total_tools > 0 else 0
            output.append(f"{i}. {tool:<30} {count:>5} calls  ({pct:>5.1f}%)")
        output.append("")
    
    # Quality Metrics
    quality = insights.get_quality_metrics()
    if quality.get("available"):
        output.append("✨ RCA QUALITY METRICS")
        output.append("-" * 70)
        output.append(f"Average Quality Score:     {quality['avg_score']:.2f}")
        output.append(f"Best Score:                {quality['max_score']:.2f}")
        output.append(f"Worst Score:               {quality['min_score']:.2f}")
        output.append(f"Reports Evaluated:         {quality['count']}")
        output.append("")
    
    output.append("=" * 70)
    output.append("💡 TIP: View detailed traces in Datadog UI:")
    output.append("   APM > LLM Observability > Sessions")
    output.append("=" * 70)
    
    return "\n".join(output)


def format_json_output(insights: InvestigationInsights, hours: int) -> str:
    """Format insights as JSON."""
    data = {
        "time_range_hours": hours,
        "overview": {
            "total_investigations": insights.get_investigation_count(),
            "avg_duration_seconds": round(insights.get_avg_duration(), 2),
            "success_rate_percent": round(insights.get_success_rate(), 1),
            "avg_iterations": round(insights.get_avg_iterations(), 1),
        },
        "token_usage": insights.get_token_usage(),
        "tool_usage": insights.get_tool_usage_stats(),
        "quality_metrics": insights.get_quality_metrics(),
    }
    
    return json.dumps(data, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Show operational insights for autonomous incident investigations"
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Time range in hours (default: 24)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    args = parser.parse_args()
    
    # Validate environment
    api_key = os.getenv("DD_API_KEY")
    app_key = os.getenv("DD_APP_KEY")
    
    if not api_key:
        print("❌ Error: DD_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)
    
    if not app_key:
        print("❌ Error: DD_APP_KEY environment variable not set", file=sys.stderr)
        print("   Create one at: https://app.datadoghq.com/organization-settings/application-keys", file=sys.stderr)
        sys.exit(1)
    
    # Query Datadog
    client = DatadogInsightsClient(api_key, app_key)
    
    print(f"🔄 Querying Datadog for investigations in the last {args.hours} hours...", file=sys.stderr)
    traces = client.query_investigation_traces(args.hours)
    
    if not traces:
        print(f"⚠️  No investigation traces found in the last {args.hours} hours.", file=sys.stderr)
        print("   Run an investigation first: python -m src.main alerts/high_error_rate.json", file=sys.stderr)
        sys.exit(0)
    
    print(f"✅ Found {len(traces)} trace spans", file=sys.stderr)
    print("", file=sys.stderr)
    
    # Analyze insights
    insights = InvestigationInsights(traces)
    
    # Output
    if args.format == "json":
        print(format_json_output(insights, args.hours))
    else:
        print(format_text_output(insights, args.hours))


if __name__ == "__main__":
    main()
