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

# ── Helper: extract clean text from Nova content blocks ───────
def extract_text(content: list) -> str:
    return '\n'.join(b['text'] for b in content if b.get('text')).strip()

# ── @llm — one Bedrock call per loop iteration ────────────────
@llm(model_name='nova-pro', model_provider='bedrock')
def call_bedrock(messages: list, tools: list) -> dict:
    LLMObs.annotate(
        input_data=[
            {
                'role': m['role'],
                'content': extract_text(m['content']) if isinstance(m['content'], list) else json.dumps(m['content'])
            }
            for m in messages
        ]
    )
    response = bedrock.invoke_model(
        modelId='amazon.nova-pro-v1:0',
        body=json.dumps({
            'messages': messages,
            'toolConfig': {
                'tools': [
                    {
                        'toolSpec': {
                            'name': t['name'],
                            'description': t.get('description', ''),
                            'inputSchema': {'json': t['input_schema']}
                        }
                    }
                    for t in tools
                ]
            },
            'inferenceConfig': {
                'max_new_tokens': 1024
            }
        }),
        contentType='application/json'
    )
    body = json.loads(response['body'].read())
    text_output = extract_text(body['output']['message']['content'])
    LLMObs.annotate(
        output_data=[{'role': 'assistant', 'content': text_output or '[tool_use]'}]
    )
    return body

# ── @tool — MCP tool execution driven by Nova's choice ────────
@tool
def execute_mcp_tool(client: DatadogMCPClient, name: str, args: dict) -> str:
    LLMObs.annotate(
        input_data=json.dumps(args, indent=2),
        tags={'tool.name': name, 'tool.source': 'datadog_mcp'}
    )
    output = client.call_tool(name, args)
    LLMObs.annotate(output_data=output)
    return output

# ── @task — extract and display the final answer ──────────────
@task
def format_final_answer(content: list) -> str:
    text = extract_text(content)
    LLMObs.annotate(
        input_data=json.dumps(content, indent=2),
        output_data=text
    )
    print(text)
    return text

# ── @workflow — root span covering the full agentic loop ───────
@workflow
def run_agent(prompt: str) -> str:
    LLMObs.annotate(input_data=prompt)

    client = DatadogMCPClient()
    client.initialize()

    raw_tools = client.list_tools()
    bedrock_tools = [
        {'name': t['name'], 'description': t.get('description', ''), 'input_schema': t['inputSchema']}
        for t in raw_tools if t['name'] == 'search_datadog_monitors'
    ]

    messages = [{'role': 'user', 'content': [{'text': prompt}]}]

    final_answer = None

    # ── Agentic loop ──────────────────────────────────────────
    while True:
        body        = call_bedrock(messages, bedrock_tools)
        stop_reason = body['stopReason']
        content     = body['output']['message']['content']

        messages.append({'role': 'assistant', 'content': content})

        if stop_reason == 'end_turn':
            final_answer = format_final_answer(content)
            break

        elif stop_reason == 'tool_use':
            tool_results = []
            for block in content:
                if 'toolUse' in block:
                    tool_use = block['toolUse']
                    print(f'[Nova calling MCP tool: {tool_use["name"]} | args: {json.dumps(tool_use["input"], indent=2)}]')
                    output = execute_mcp_tool(client, tool_use['name'], tool_use['input'])
                    tool_results.append({
                        'toolResult': {
                            'toolUseId': tool_use['toolUseId'],
                            'content': [{'text': output}]
                        }
                    })
            messages.append({'role': 'user', 'content': tool_results})

    LLMObs.annotate(output_data=final_answer)
    return final_answer

if __name__ == '__main__':
    run_agent('What Datadog monitors are currently alerting? Summarise them and suggest a priority order to investigate.')
    LLMObs.flush()
    # Trace now visible in: app.datadoghq.com/llm/traces
