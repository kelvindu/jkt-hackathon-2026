import boto3, json, os
from dotenv import load_dotenv
from ddtrace.llmobs import LLMObs

load_dotenv()

LLMObs.enable(
    ml_app=os.environ['DD_LLMOBS_ML_APP'],
    agentless_enabled=True,
    api_key=os.environ['DD_API_KEY'],
    site=os.environ.get('DD_SITE', 'datadoghq.com')
)

client = boto3.client('bedrock-runtime', region_name=os.environ['AWS_REGION'])

def ask(prompt: str) -> str:
    response = client.invoke_model(
        modelId='amazon.nova-pro-v1:0',
        body=json.dumps({
            'messages': [
                {'role': 'user', 'content': [{'text': prompt}]}
            ],
            'inferenceConfig': {
                'max_new_tokens': 1024
            }
        }),
        contentType='application/json'
    )
    result = json.loads(response['body'].read())
    return result['output']['message']['content'][0]['text']

if __name__ == '__main__':
    print(ask('What makes an AI system production-ready?'))
    LLMObs.flush()
