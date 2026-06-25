# Hackathon Scoring Checklist & Knowledge Base

This is a memory/reference file for the Jakarta Hackathon 2026 (Datadog x AWS). Use it to track progress, know what's needed for each checkpoint, and avoid missing points.

---

## Quick Facts

- **Total possible points:** 2700 (Datadog 1500 + AWS 1200) + First Blood bonuses + Innovation/Presentation
- **First Blood:** +50 pts for the first team to complete any individual task
- **Model in use:** `amazon.nova-pro-v1:0` (Bedrock)
- **DD LLM Observability URL:** https://app.datadoghq.com/llm/traces
- **DD MCP Server:** https://mcp.datadoghq.com/api/unstable/mcp-server/mcp
- **Key Python packages:** `ddtrace`, `boto3`, `python-dotenv`, `requests`
- **Key decorators from ddtrace:** `@workflow`, `@llm`, `@tool`, `@task`

---

## 🐶 Datadog Tasks — 1500 pts

### 1. 🟢 First Trace — 100 pts
- [ ] **Status:** NOT DONE
- **What:** First LLM span visible in Datadog LLM Observability from YOUR app (not starter scripts)
- **How to earn:**
  - Use `LLMObs.enable(...)` with agentless mode
  - Make at least one Bedrock call
  - Call `LLMObs.flush()` at the end
  - Verify span in https://app.datadoghq.com/llm/traces filtered by your `DD_LLMOBS_ML_APP`
- **Key code pattern:**
  ```python
  from ddtrace.llmobs import LLMObs
  LLMObs.enable(ml_app=..., agentless_enabled=True, api_key=..., site=...)
  # ... make your LLM call ...
  LLMObs.flush()
  ```
- **IMPORTANT:** Must come from your actual application, not the starter repo scripts

### 2. 📊 Dashboard Live — 150 pts
- [ ] **Status:** NOT DONE
- **What:** Custom Datadog dashboard with ≥3 widgets showing live data
- **How to earn:**
  - Modify `shared/dashboard.tf` or create your own dashboard config
  - Must have at least 3 widgets with live data
  - Deploy via `terraform apply` in `shared/` directory
  - Dashboard title should be distinguishable from the starter
- **Starter widgets available:** Request Rate, P95 Latency, Total Tokens, Error Rate
- **IMPORTANT:** Must be from actual modification, not the unmodified starter dashboard

### 3. 🔗 Tool Call Visible — 200 pts
- [ ] **Status:** NOT DONE
- **What:** An agent tool call captured as a span in Datadog
- **How to earn:**
  - Use `@tool` decorator on a function that acts as a tool call
  - Use `LLMObs.annotate(...)` to tag input/output
  - The tool span must be visible nested inside a workflow span
- **Key pattern:**
  ```python
  @tool
  def my_tool_function(args):
      LLMObs.annotate(input_data=..., output_data=..., tags={...})
      # do the tool work
      return result
  ```
- **IMPORTANT:** Must be from your app, not the starter

### 4. 💸 Cost Tracked — 200 pts
- [ ] **Status:** NOT DONE
- **What:** Token/cost metrics visible in Datadog dashboard AND in LLM trace
- **How to earn:**
  - Annotate LLM spans with token usage metadata
  - Add cost widget to dashboard
  - Cost should be visible when inspecting a trace in LLM Observability
- **Tip:** Use `LLMObs.annotate(metrics={"input_tokens": X, "output_tokens": Y, "total_tokens": Z})` if supported, or add token counts as tags

### 5. 🧱 Error Handled — 250 pts
- [ ] **Status:** NOT DONE
- **What:** Graceful error shown in app trace + monitor/alert configured
- **How to earn:**
  - Implement error handling in your app that catches failures gracefully
  - The error must appear as a span in the trace (not crash the app)
  - Configure a Datadog Monitor that alerts when errors accumulate
- **Two parts:** (1) trace shows graceful error, (2) monitor/alert responds to accumulated errors

### 6. 🚀 End-to-End Demo — 300 pts
- [ ] **Status:** NOT DONE
- **What:** Full workflow running with observability — complete trace with decorators on workflow, tool, tasks, and LLM calls
- **How to earn:**
  - Build a complete feature/workflow in your app
  - Use ALL decorator types: `@workflow`, `@tool`, `@task`, `@llm`
  - Show the full trace in LLM Observability explorer
  - Expected span tree:
    ```
    workflow: your_main_workflow
    ├── tool: some_tool_call
    ├── llm: bedrock_call
    ├── task: processing_step
    └── ...
    ```
- **This is the big one** — demonstrates full mastery of LLM Observability

### 7. 🎯 Ops Ready Bonus — 300 pts
- [ ] **Status:** NOT DONE
- **What:** Monitor Runbook + alert policy to on-call team + SLO all defined
- **How to earn:**
  - Create a Monitor with a Runbook (instructions for responders)
  - Set up alert routing to an on-call team/channel
  - Define an SLO (Service Level Objective) in Datadog
- **All three required:** Runbook, Alert Policy, SLO

---

## ☁️ AWS Tasks — 1200 pts

### 1. ✅ Bedrock Online — 100 pts
- [ ] **Status:** NOT DONE
- **What:** One successful Bedrock model response in the terminal
- **How to earn:**
  - Run any script that calls Bedrock and prints a response
  - Show the output in the terminal
- **Quickest win:** `python track-aiops/basic-bedrock-call.py` (but for scoring, use your own app)

### 2. 📖 AWS Knowledge MCP Configured — 100 pts
- [ ] **Status:** NOT DONE
- **What:** MCP config listing the AWS Knowledge server + one question answered that shaped your design
- **How to earn:**
  - Add AWS documentation MCP server to your Kiro/editor MCP config
  - Show that you asked a question and it influenced a design decision
- **MCP config example:**
  ```json
  {
    "mcpServers": {
      "aws-docs": {
        "command": "uvx",
        "args": ["awslabs.aws-documentation-mcp-server@latest"],
        "env": { "FASTMCP_LOG_LEVEL": "ERROR" }
      }
    }
  }
  ```

### 3. 🏗️ Built with Kiro — 100 pts
- [ ] **Status:** PARTIALLY DONE (this file exists in .kiro)
- **What:** Open `.kiro` folder — show a spec/steering file and generated code
- **How to earn:**
  - Have meaningful content in `.kiro/` (specs, steering files)
  - Show that Kiro was used to generate/guide code
  - This file counts towards it!

### 4. 🧠 Multi-Step Agent — 200 pts
- [ ] **Status:** NOT DONE
- **What:** Run agent once — show ≥2 sequential reason→act steps for a single request
- **How to earn:**
  - Build an agentic loop where the LLM decides to call tools iteratively
  - Show at least 2 turns of reasoning + action before final answer
  - The `bedrock-mcp-agent.py` pattern demonstrates this (LLM→tool→LLM→answer)
- **Key:** Must be 2+ sequential reason→act loops, not just one tool call

### 5. 📚 Knowledge Grounded — 300 pts
- [ ] **Status:** NOT DONE
- **What:** Ask agent something only YOUR data knows — show Knowledge Base or retrieval call
- **How to earn:**
  - Set up an AWS Bedrock Knowledge Base with your own data
  - OR implement RAG (Retrieval Augmented Generation) with your own documents
  - Show the agent answering a question it can ONLY answer from your data
  - The retrieval/KB call must be visible in the workflow

### 6. 🛡️ Guardrails On — 200 pts
- [ ] **Status:** NOT DONE
- **What:** Send a prompt that should be blocked — show Bedrock Guardrails filtering it
- **How to earn:**
  - Configure AWS Bedrock Guardrails (content filters, denied topics, etc.)
  - Send a prompt that triggers the guardrail
  - Show the blocked/filtered response
- **Setup:** AWS Console → Bedrock → Guardrails → Create guardrail

### 7. 🌏 Jakarta In-Region — 200 pts
- [ ] **Status:** NOT DONE
- **What:** Show model usage using models available in Jakarta region (ap-southeast-3)
- **How to earn:**
  - Change `AWS_REGION` to `ap-southeast-3` (or use Jakarta endpoint)
  - Use a model available in that region
  - Show successful invocation from Jakarta region
- **Note:** Not all models are available in Jakarta — check Bedrock console for ap-southeast-3 availability

---

## Environment Variables Required

```dotenv
DD_API_KEY=<Datadog API key>
DD_APP_KEY=<Datadog Application key>
DD_SITE=datadoghq.com
DD_LLMOBS_ENABLED=1
DD_LLMOBS_AGENTLESS_ENABLED=1
DD_LLMOBS_ML_APP=<your-team-name>
AWS_ACCESS_KEY_ID=<AWS key>
AWS_SECRET_ACCESS_KEY=<AWS secret>
AWS_REGION=us-east-1
```

---

## Key Patterns & Code References

### Enabling LLM Observability (agentless)
```python
from ddtrace.llmobs import LLMObs
LLMObs.enable(
    ml_app=os.environ['DD_LLMOBS_ML_APP'],
    agentless_enabled=True,
    api_key=os.environ['DD_API_KEY'],
    site=os.environ.get('DD_SITE', 'datadoghq.com')
)
```

### Decorator hierarchy (span types)
```python
from ddtrace.llmobs.decorators import llm, tool, workflow, task

@workflow        # Root span — ties everything together
@tool            # Non-LLM step that feeds the LLM (retrieval, API calls)
@llm(model_name='nova-pro', model_provider='bedrock')  # Actual LLM call
@task            # Non-LLM processing step (formatting, validation)
```

### Annotating spans
```python
LLMObs.annotate(
    input_data="the input",
    output_data="the output",
    tags={'custom.tag': 'value'}
)
```

### Calling Bedrock (Nova Pro)
```python
client = boto3.client('bedrock-runtime', region_name=os.environ['AWS_REGION'])
response = client.invoke_model(
    modelId='amazon.nova-pro-v1:0',
    body=json.dumps({
        'messages': [{'role': 'user', 'content': [{'text': prompt}]}],
        'inferenceConfig': {'max_new_tokens': 1024}
    }),
    contentType='application/json'
)
```

### Agentic loop pattern (from bedrock-mcp-agent.py)
```
while True:
    response = call_bedrock(messages, tools)
    if stop_reason == 'end_turn': break
    elif stop_reason == 'tool_use': execute tool, append results, loop
```

### Terraform dashboard deployment
```bash
cd shared/
terraform init
terraform apply -var="datadog_api_key=..." -var="datadog_app_key=..." -var="team_name=..."
```

---

## Priority Order (bang for buck)

| Priority | Task | Points | Difficulty |
|----------|------|--------|------------|
| 1 | Bedrock Online (AWS #1) | 100 | Easy |
| 2 | First Trace (DD #1) | 100 | Easy |
| 3 | Built with Kiro (AWS #3) | 100 | Easy |
| 4 | Dashboard Live (DD #2) | 150 | Easy |
| 5 | AWS Knowledge MCP (AWS #2) | 100 | Easy |
| 6 | Tool Call Visible (DD #3) | 200 | Medium |
| 7 | Cost Tracked (DD #4) | 200 | Medium |
| 8 | Multi-Step Agent (AWS #4) | 200 | Medium |
| 9 | Guardrails On (AWS #6) | 200 | Medium |
| 10 | Jakarta In-Region (AWS #7) | 200 | Medium |
| 11 | Error Handled (DD #5) | 250 | Medium-Hard |
| 12 | End-to-End Demo (DD #6) | 300 | Hard |
| 13 | Knowledge Grounded (AWS #5) | 300 | Hard |
| 14 | Ops Ready Bonus (DD #7) | 300 | Hard |

---

## Reminders & Gotchas

- Scoring checkpoints require traces/dashboards from YOUR application, NOT the starter scripts
- Always call `LLMObs.flush()` at the end of your scripts
- Traces take ~30-60 seconds to appear in Datadog
- MCP server requires BOTH `DD_API_KEY` and `DD_APP_KEY`
- Dashboard must be modified from starter to earn points (can't just deploy the default)
- For Jakarta region (AWS #7), check which models are available in ap-southeast-3
- First Blood (+50) rewards speed — prioritize quick wins first
- Innovation & Presentation scored by facilitators at the end — build something meaningful
