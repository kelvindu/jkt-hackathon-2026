import boto3, json, os, requests
from dotenv import load_dotenv
from ddtrace.llmobs import LLMObs
from ddtrace.llmobs.decorators import llm, tool, workflow, task

load_dotenv()

# ── Enable LLM Observability ─────────────────────────────────
LLMObs.enable(
    ml_app=os.environ['DD_LLMOBS_ML_APP'],
    agentless_enabled=True,
    api_key=os.environ['DD_API_KEY'],
    site=os.environ.get('DD_SITE', 'datadoghq.com')
)

bedrock = boto3.client('bedrock-runtime', region_name=os.environ['AWS_REGION'])

DD_MCP_URL = 'https://mcp.datadoghq.com/api/unstable/mcp-server/mcp'
DD_HEADERS = {
    'Content-Type': 'application/json',
    'DD-API-KEY': os.environ['DD_API_KEY'],
    'DD-APPLICATION-KEY': os.environ['DD_APP_KEY'],
}

# ── Minimal JSON-RPC client for the Datadog MCP server ────────
class DatadogMCPClient:
    def __init__(self):
        self._id = 0
        self._session_id = None

    def _post(self, method: str, params: dict = None) -> dict:
        self._id += 1
        payload = {'jsonrpc': '2.0', 'id': self._id, 'method': method, 'params': params or {}}
        headers = {
            **DD_HEADERS,
            'Accept': 'application/json, text/event-stream'
        }
        if self._session_id:
            headers['Mcp-Session-Id'] = self._session_id
        response = requests.post(DD_MCP_URL, json=payload, headers=headers)
        response.raise_for_status()
        # Capture session ID returned by the server on initialize
        if 'Mcp-Session-Id' in response.headers:
            self._session_id = response.headers['Mcp-Session-Id']
        return response.json()

    def initialize(self):
        self._post('initialize', {
            'protocolVersion': '2024-11-05',
            'capabilities': {},
            'clientInfo': {'name': 'bedrock-mcp-agent', 'version': '1.0'}
        })

    def list_tools(self) -> list:
        result = self._post('tools/list')
        return result.get('result', {}).get('tools', [])

    def call_tool(self, name: str, arguments: dict) -> str:
        result = self._post('tools/call', {'name': name, 'arguments': arguments})
        content = result.get('result', {}).get('content', [])
        return content[0].get('text', '') if content else ''

# ── @llm — one Bedrock call per loop iteration ────────────────
@llm(model_name='claude-3-sonnet', model_provider='bedrock')
def call_bedrock(messages: list, tools: list) -> dict:
    LLMObs.annotate(
        input_data=[{'role': m['role'], 'content': json.dumps(m['content'])}
                    for m in messages]
    )
    response = bedrock.invoke_model(
        modelId='anthropic.claude-3-sonnet-20240229-v1:0',
        body=json.dumps({
            'anthropic_version': 'bedrock-2023-05-31',
            'max_tokens': 1024,
            'tools': tools,
            'messages': messages
        }),
        contentType='application/json'
    )
    body = json.loads(response['body'].read())
    text_output = ' '.join(b['text'] for b in body['content'] if b.get('type') == 'text')
    LLMObs.annotate(
        output_data=[{'role': 'assistant', 'content': text_output or '[tool_use]'}]
    )
    return body

# ── @tool — MCP tool execution driven by Bedrock's choice ─────
@tool
def execute_mcp_tool(client: DatadogMCPClient, name: str, args: dict) -> str:
    LLMObs.annotate(
        input_data=json.dumps(args),
        tags={'tool.name': name, 'tool.source': 'datadog_mcp'}
    )
    output = client.call_tool(name, args)
    LLMObs.annotate(output_data=output)
    return output

# ── @task — extract and display the final answer ──────────────
@task
def format_final_answer(content: list) -> str:
    text = ' '.join(b['text'] for b in content if b.get('type') == 'text')
    LLMObs.annotate(input_data=json.dumps(content), output_data=text)
    print(text)
    return text

# ── @workflow — root span covering the full agentic loop ───────
@workflow
def run_agent(prompt: str):
    client = DatadogMCPClient()
    client.initialize()

    raw_tools = client.list_tools()
    bedrock_tools = [
        {'name': t['name'], 'description': t.get('description', ''), 'input_schema': t['inputSchema']}
        for t in raw_tools if t['name'] == 'search_datadog_monitors'
    ]

    messages = [{'role': 'user', 'content': prompt}]

    # ── Agentic loop ──────────────────────────────────────────
    while True:
        body        = call_bedrock(messages, bedrock_tools)
        stop_reason = body['stop_reason']
        content     = body['content']

        messages.append({'role': 'assistant', 'content': content})

        if stop_reason == 'end_turn':
            format_final_answer(content)
            break

        elif stop_reason == 'tool_use':
            tool_results = []
            for block in content:
                if block['type'] == 'tool_use':
                    print(f'[Bedrock calling MCP tool: {block["name"]} | args: {block["input"]}]')
                    output = execute_mcp_tool(client, block['name'], block['input'])
                    tool_results.append({
                        'type': 'tool_result',
                        'tool_use_id': block['id'],
                        'content': output
                    })
            messages.append({'role': 'user', 'content': tool_results})

if __name__ == '__main__':
    run_agent('What Datadog monitors are currently alerting? Summarise them and suggest a priority order to investigate.')
    LLMObs.flush()
    # Trace now visible in: app.datadoghq.com/llm/traces
