import boto3, json, os
from dotenv import load_dotenv
from ddtrace.llmobs import LLMObs
 
load_dotenv()
 
# ── 2 lines to enable LLM Observability ─────────────────────
LLMObs.enable(
    ml_app=os.environ['DD_LLMOBS_ML_APP'],
    agentless_enabled=True,
    api_key=os.environ['DD_API_KEY'],
    site=os.environ.get('DD_SITE', 'datadoghq.com')
)
 
client = boto3.client('bedrock-runtime', region_name=os.environ['AWS_REGION'])
 
def ask(prompt: str) -> str:
    response = client.invoke_model(
        modelId='anthropic.claude-3-sonnet-20240229-v1:0',
        body=json.dumps({
            'anthropic_version': 'bedrock-2023-05-31',
            'max_tokens': 512,
            'messages': [{'role': 'user', 'content': prompt}]
        }),
        contentType='application/json'
    )
    return json.loads(response['body'].read())['content'][0]['text']
 
if __name__ == '__main__':
    print(ask('What makes an AI system production-ready?'))
    LLMObs.flush()   # Flush before process exits
    # Trace now visible in: app.datadoghq.com/llm/traces
