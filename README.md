# Jakarta Hackathon — LLM Observability with Datadog

This guide walks you through setting up your environment and running the Track: AIOps sample scripts to see how LLM traces and spans appear in Datadog LLM Observability. By the end you will have three working traces in Datadog and a live starter dashboard deployed via Terraform.

---

## Folder Structure

```
jkt-hackathon-2026/
├── .env.template              # Copy this to .env and fill in your credentials
├── shared/
│   ├── dashboard.tf           # Terraform config for your starter dashboard
│   └── variables.tf           # Terraform variable definitions
└── track-aiops/
    ├── basic-bedrock-call.py        # Step 1 — basic LLM trace
    ├── bedrock-decorator-example.py # Step 2 — traces with span decorators
    └── bedrock-mcp-agent.py         # Step 3 — agentic MCP call to Datadog
```

---

## Section 1 — Set Up Environment Variables

All scripts read credentials from a `.env` file in the `jkt-hackathon-2026/` root. A template is provided for you to fill in.

**1.1** From the `jkt-hackathon-2026/` directory, copy the template to create your own `.env` file:

```bash
cp .env.template .env
```

**1.2** Open `.env` in any text editor and replace every placeholder with your real values:

```dotenv
# ── Datadog ───────────────────────────────────────────────────
DD_API_KEY=<YOUR_DATADOG_API_KEY>         # Found in Datadog → Organization Settings → API Keys
DD_APP_KEY=<YOUR_DATADOG_APP_KEY>         # Found in Datadog → Organization Settings → Application Keys
DD_SITE=datadoghq.com
DD_LLMOBS_ENABLED=1
DD_LLMOBS_AGENTLESS_ENABLED=1            # No local Datadog Agent needed
DD_LLMOBS_ML_APP=jakarta-hack-<TEAM_NAME> # Replace <TEAM_NAME> with your team name e.g. jakarta-hack-team-alpha

# ── AWS ───────────────────────────────────────────────────────
AWS_ACCESS_KEY_ID=<YOUR_AWS_KEY>
AWS_SECRET_ACCESS_KEY=<YOUR_AWS_SECRET>
AWS_REGION=us-east-1
```

> **Note:** Never commit your `.env` file. It is already excluded from version control.

---

## Section 2 — Install Prerequisites

### Python

Ensure you have **Python 3.9 or later** installed:

```bash
python3 --version
```

If Python is not installed, download it from [python.org](https://www.python.org/downloads/) or install via Homebrew on macOS:

```bash
brew install python
```

**Create and activate a virtual environment** from the `jkt-hackathon-2026/` directory:

```bash
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
```

You should see `(.venv)` prefix in your terminal prompt confirming the environment is active.

**Install all required Python packages:**

```bash
pip install ddtrace boto3 python-dotenv requests
```

| Package | Purpose |
|---|---|
| `ddtrace` | Datadog tracing library — provides `LLMObs` and span decorators |
| `boto3` | AWS SDK — used to call Claude via Amazon Bedrock |
| `python-dotenv` | Loads your `.env` file into environment variables |
| `requests` | HTTP client — used to call the Datadog MCP server directly |

### Terraform

Terraform is required for Section 4 to deploy your starter dashboard.

**macOS (Homebrew):**

```bash
brew tap hashicorp/tap
brew install hashicorp/tap/terraform
```

**Linux:**

```bash
sudo apt-get update && sudo apt-get install -y gnupg software-properties-common
wget -O- https://apt.releases.hashicorp.com/gpg | gpg --dearmor | sudo tee /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt-get update && sudo apt-get install terraform
```

Verify the installation:

```bash
terraform -version
```

---

## Section 3 — Run the Track: AIOps Sample Scripts

All three scripts must be run from the `jkt-hackathon-2026/` root directory so they can locate your `.env` file. Make sure your virtual environment is active before running any script.

```bash
cd jkt-hackathon-2026/
source .venv/bin/activate
```

---

### Script 1 — Basic LLM Trace (`basic-bedrock-call.py`)

This script demonstrates the minimum code needed to send a single LLM call to Amazon Bedrock and have it appear as a trace in Datadog LLM Observability. It shows how to enable `LLMObs` in agentless mode with just a few lines.

**Run:**

```bash
python track-aiops/basic-bedrock-call.py
```

**What to expect:**

- The terminal will print the model's response to the prompt `"What makes an AI system production-ready?"`
- A single LLM trace will appear in Datadog within ~30 seconds

**View your trace in Datadog:**

1. Go to [app.datadoghq.com/llm/traces](https://app.datadoghq.com/llm/traces)
2. Filter by your ML app name (the value you set for `DD_LLMOBS_ML_APP` in `.env`)
3. You should see one trace with a single `llm` span showing the input prompt and model response

---

### Script 2 — Advanced Trace with Span Decorators (`bedrock-decorator-example.py`)

This script builds on Script 1 by introducing `ddtrace` span decorators — `@workflow`, `@llm`, `@tool`, and `@task`. Each decorator marks a function as a specific type of span, giving you a structured, nested trace in Datadog rather than a single flat span.

**Run:**

```bash
python track-aiops/bedrock-decorator-example.py
```

**What to expect:**

- The terminal will print the model's response along with a word count
- A structured trace with four nested spans will appear in Datadog

**View your trace in Datadog:**

1. Go to [app.datadoghq.com/llm/traces](https://app.datadoghq.com/llm/traces)
2. Open the latest trace for your ML app — you should see the following span tree:

```
workflow: run_pipeline
├── tool: fetch_context       ← retrieves a system instruction
├── llm: ask                  ← the Bedrock call with input/output annotated
└── task: process_result      ← post-processing step with word count tag
```

This structure gives you visibility into each stage of your pipeline, not just the LLM call itself.

---

### Script 3 — Agentic MCP Call to Datadog (`bedrock-mcp-agent.py`)

This script demonstrates a true agentic loop where Bedrock itself decides to call a tool — in this case the **Datadog MCP server** — to fetch live monitor data before generating its final answer. The LLM is not just receiving pre-fetched data; it is driving the tool call.

> **Additional credential required:** This script calls the Datadog MCP server and requires `DD_APP_KEY` to be set in your `.env`, in addition to `DD_API_KEY`. Confirm both are filled in before running.

**Run:**

```bash
python track-aiops/bedrock-mcp-agent.py
```

**What to expect:**

- The terminal will first print a line showing Bedrock choosing to call the MCP tool, for example:
  `[Bedrock calling MCP tool: search_datadog_monitors | args: {'query': 'status:alert'}]`
- Bedrock will then receive the live monitor results and print a prioritised summary
- A multi-span trace will appear in Datadog showing the full agentic loop

**View your trace in Datadog:**

1. Go to [app.datadoghq.com/llm/traces](https://app.datadoghq.com/llm/traces)
2. Open the latest trace — you should see:

```
workflow: run_agent
├── llm: call_bedrock          ← first turn: Bedrock decides to call the tool
├── tool: execute_mcp_tool     ← live call to Datadog MCP (search_datadog_monitors)
├── llm: call_bedrock          ← second turn: Bedrock receives results and answers
└── task: format_final_answer  ← final answer extraction and display
```

The two `llm` spans represent the two turns of the agentic loop — the first where Bedrock chooses to call a tool, and the second where it uses the tool result to produce its final answer.

---

## Section 4 — Deploy Your Starter Dashboard with Terraform

The `shared/` directory contains a Terraform configuration that creates an **LLM Observability starter dashboard** in your Datadog account. The dashboard includes widgets for request rate, P95 latency, total token usage, and error rate.

**4.1** Navigate to the `shared/` directory:

```bash
cd shared/
```

**4.2** Initialise Terraform to download the Datadog provider:

```bash
terraform init
```

You should see a message confirming the Datadog provider has been installed.

**4.3** Apply the configuration. Terraform will prompt you for three values:

```bash
terraform apply
```

When prompted, enter:

- `datadog_api_key` — your Datadog API key (same as `DD_API_KEY` in your `.env`)
- `datadog_app_key` — your Datadog Application key (same as `DD_APP_KEY` in your `.env`)
- `team_name` — your team name, e.g. `team-alpha`

Review the plan Terraform prints, then type `yes` to confirm and deploy.

**4.4** Once apply completes, log in to Datadog and navigate to **Dashboards**. You will find a new dashboard titled **"Jakarta Hackathon — LLM Observability Starter"** with four pre-built widgets. Data will populate as you run the scripts above.

> **Tip:** To pass values without being prompted interactively, you can supply them as flags:
> ```bash
> terraform apply \
>   -var="datadog_api_key=YOUR_API_KEY" \
>   -var="datadog_app_key=YOUR_APP_KEY" \
>   -var="team_name=team-alpha"
> ```

---

## Troubleshooting

**No traces appearing in Datadog**
- Confirm `DD_API_KEY` and `DD_LLMOBS_ML_APP` are correctly set in `.env`
- Traces can take up to 60 seconds to appear — refresh the LLM Traces page
- Ensure `LLMObs.flush()` is present at the end of the script (all three scripts include this)

**400 error from MCP server (`bedrock-mcp-agent.py`)**
- Confirm `DD_APP_KEY` is set in your `.env` — the MCP server requires both API key and App key
- Ensure you are using the correct `DD_SITE` value for your Datadog organisation

**Bedrock `AccessDeniedException`**
- Confirm `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are correct in `.env`
- Ensure the `amazon.nova-pro-v1:0` model is enabled in your AWS Bedrock console under **Model access** in the region you use

**Terraform `Error: Invalid credentials`**
- Double-check that the API key and App key entered during `terraform apply` match those in your Datadog account
- Application keys must have the `dashboards_write` permission scope
