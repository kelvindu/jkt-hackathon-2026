"""Agent loop tests with a mocked Bedrock client (no AWS/network needed).

Verifies the multi-step reason->act->remediate flow, cost accounting, and that
the RCA promotes the blast radius to CONFIRMED with remediation noted.
"""

from app.agent import InvestigationAgent
from app.bedrock_client import BedrockResponse, ToolUse
from app.config import load
from app.scenarios import load_scenarios


class FakeBedrock:
    """Scripted Converse client: health check -> remediate -> final summary."""

    model_id = "amazon.nova-pro-v1:0"

    def __init__(self):
        self.calls = 0

    @staticmethod
    def format_message(role, content):
        if isinstance(content, str):
            content = [{"text": content}]
        return {"role": role, "content": content}

    def converse(self, messages, tool_config=None, system=None, guardrail_config=None):
        self.calls += 1
        usage = {"inputTokens": 100, "outputTokens": 50, "totalTokens": 150}
        if self.calls == 1:
            msg = {"role": "assistant", "content": [
                {"text": "Checking auth-service health first."},
                {"toolUse": {"toolUseId": "t1", "name": "query_service_health", "input": {"service": "auth-service"}}},
            ]}
            return BedrockResponse(msg, "tool_use", usage, [ToolUse("t1", "query_service_health", {"service": "auth-service"})])
        if self.calls == 2:
            msg = {"role": "assistant", "content": [
                {"text": "Confirmed DB timeout. Remediating."},
                {"toolUse": {"toolUseId": "t2", "name": "remediate_disable_chaos", "input": {"service": "auth-service"}}},
            ]}
            return BedrockResponse(msg, "tool_use", usage, [ToolUse("t2", "remediate_disable_chaos", {"service": "auth-service"})])
        msg = {"role": "assistant", "content": [
            {"text": "WHAT BROKE: DB connection-pool timeout in AuthValidationService.\n"
                     "WHAT IT COSTS: 42 customers stuck, $145/min.\n"
                     "RECOMMENDED ACTION: chaos disabled, recovery verified."},
        ]}
        return BedrockResponse(msg, "end_turn", usage, [])


def test_multi_step_investigation_remediates(monkeypatch):
    # Tools must not hit the network: stub execute_tool.
    import app.agent as agent_mod

    def fake_execute(name, args):
        if name == "query_service_health":
            return {"success": True, "result": {"service": "auth-service", "healthy": False}}
        if name == "remediate_disable_chaos":
            return {"success": True, "result": {"service": "auth-service", "remediated": True}}
        return {"success": False, "error": "unexpected"}

    monkeypatch.setattr(agent_mod, "execute_tool", fake_execute)

    settings = load(require=False)
    scenario = load_scenarios("alerts/auth_service_timeout.json")[0]
    agent = InvestigationAgent(FakeBedrock(), settings)
    report = agent.investigate(scenario)

    assert report.remediated is True
    assert report.iterations_used == 3  # two tool turns + final summary
    assert report.total_tokens == 450  # 3 * 150
    assert report.total_cost_usd > 0
    assert report.blast_radius is not None
    assert report.blast_radius.technical.status == "confirmed"
    assert "WHAT BROKE" in report.investigation_summary
