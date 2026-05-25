import boto3, json, os
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

client = boto3.client('bedrock-runtime', region_name=os.environ['AWS_REGION'])

# ── @workflow ties everything together as the root span ───────
@workflow
def run_pipeline(prompt: str) -> str:
    context = fetch_context(prompt)
    response = ask(prompt, context)
    return process_result(response)

# ── @tool marks a non-LLM step that feeds into the LLM call ──
@tool
def fetch_context(prompt: str) -> str:
    LLMObs.annotate(
        input_data=prompt,
        output_data='Keep answers concise and practical.',
        tags={'context.type': 'system_instruction'}
    )
    return 'Keep answers concise and practical.'

# ── @llm marks the actual LLM call as an LLM span ────────────
@llm(model_name='claude-3-sonnet', model_provider='bedrock')
def ask(prompt: str, context: str) -> str:
    messages = [
        {'role': 'user', 'content': f'{context}\n\n{prompt}'}
    ]
    LLMObs.annotate(
        input_data=[{'role': 'user', 'content': f'{context}\n\n{prompt}'}]
    )
    response = client.invoke_model(
        modelId='anthropic.claude-3-sonnet-20240229-v1:0',
        body=json.dumps({
            'anthropic_version': 'bedrock-2023-05-31',
            'max_tokens': 512,
            'messages': messages
        }),
        contentType='application/json'
    )
    result = json.loads(response['body'].read())['content'][0]['text']

    LLMObs.annotate(
        output_data=[{'role': 'assistant', 'content': result}]
    )
    return result

# ── @task marks a non-LLM processing step ────────────────────
@task
def process_result(response: str) -> str:
    word_count = len(response.split())
    LLMObs.annotate(
        input_data=response,
        output_data=response,
        tags={'word_count': str(word_count)}
    )
    print(f'[Response — {word_count} words]\n{response}')
    return response

if __name__ == '__main__':
    run_pipeline('What makes an AI system production-ready?')
    LLMObs.flush()   # Flush before process exits
    # Trace now visible in: app.datadoghq.com/llm/traces
