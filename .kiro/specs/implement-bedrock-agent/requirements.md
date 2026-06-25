# Requirements Document

## Introduction

The `track_aiops` package provides a CLI interface to invoke the AWS Bedrock Nova Pro model and emit LLM observability spans to Datadog. It serves as the foundational component for the Jakarta Hackathon 2026 (Datadog x AWS) scoring checkpoints: Bedrock Online (100pts) and First Trace (100pts).

## Glossary

- **CLI**: The command-line interface entry point invoked via `python -m track_aiops.cli ask "..."`
- **BedrockClient**: The module wrapping boto3 for AWS Bedrock model invocation
- **LLMObs**: The Datadog LLM Observability SDK used to enable tracing and flush spans
- **Settings**: The configuration dataclass holding validated environment variables
- **Span**: A Datadog trace unit representing a single LLM invocation with metadata
- **BedrockResponse**: A dataclass containing the model response text, token usage, and stop reason

## Requirements

### Requirement 1: CLI Entry Point

**User Story:** As a developer, I want to invoke the Bedrock model from the command line, so that I can quickly test prompts and demonstrate model connectivity.

#### Acceptance Criteria

1. WHEN a user runs `python -m track_aiops.cli ask "<prompt>"`, THE CLI SHALL invoke the Bedrock model with the provided prompt and print the response text to stdout
2. WHEN the CLI completes successfully, THE CLI SHALL exit with code 0
3. WHEN the CLI encounters an error, THE CLI SHALL print a descriptive error message to stderr and exit with a non-zero code
4. WHEN the CLI is invoked without a prompt argument, THE CLI SHALL display a usage message and exit with a non-zero code

### Requirement 2: Configuration and Validation

**User Story:** As a developer, I want configuration loaded from environment variables with fail-fast validation, so that I get immediate feedback when required credentials are missing.

#### Acceptance Criteria

1. WHEN `config.load()` is called, THE Settings module SHALL load environment variables from a `.env` file using python-dotenv
2. WHEN any required environment variable is missing (DD_API_KEY, DD_LLMOBS_ML_APP, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY), THE Settings module SHALL raise an error naming the exact missing variable
3. WHEN optional environment variables are absent, THE Settings module SHALL apply defaults: AWS_REGION defaults to `us-east-1` and DD_SITE defaults to `datadoghq.com`
4. THE Settings module SHALL expose DD_API_KEY, DD_LLMOBS_ML_APP, AWS_REGION, and DD_SITE as fields on the Settings dataclass

### Requirement 3: Bedrock Model Invocation

**User Story:** As a developer, I want to call AWS Bedrock Nova Pro and receive a structured response, so that I can demonstrate model connectivity and use the response in my application.

#### Acceptance Criteria

1. WHEN `BedrockClient.invoke(prompt)` is called with a valid prompt, THE BedrockClient SHALL send a request to the `amazon.nova-pro-v1:0` model via boto3 `invoke_model`
2. WHEN the model returns a successful response, THE BedrockClient SHALL parse it into a BedrockResponse containing text, token usage (input_tokens, output_tokens, total_tokens), and stop_reason
3. IF the AWS credentials are invalid or the region is unreachable, THEN THE BedrockClient SHALL raise a BedrockAuthError with a message hinting the user to check credentials and region
4. IF the model response body is malformed or missing expected fields, THEN THE BedrockClient SHALL raise a BedrockResponseError with a descriptive message
5. THE BedrockClient SHALL construct the request body using the Nova family message format with `inferenceConfig.max_new_tokens` set to 1024

### Requirement 4: Datadog LLM Observability Integration

**User Story:** As a developer, I want every Bedrock invocation to emit an LLM span to Datadog, so that I can verify observability is working and earn the First Trace checkpoint.

#### Acceptance Criteria

1. WHEN the application starts, THE Observability module SHALL call `LLMObs.enable` with agentless mode, the configured ml_app name, API key, and site
2. WHEN the traced LLM function is invoked, THE Observability module SHALL create a span with model_name `nova-pro` and model_provider `bedrock`
3. WHEN a Bedrock call completes successfully, THE Observability module SHALL annotate the span with input_data (the prompt), output_data (the response text), and metrics (input_tokens, output_tokens, total_tokens)
4. WHEN the application exits, THE Observability module SHALL call `LLMObs.flush()` in a finally block to ensure spans are submitted regardless of success or failure
5. THE Observability module SHALL have no dependency on CLI or IO concerns

### Requirement 5: Module Separation

**User Story:** As a developer, I want clean module boundaries so that each component can evolve independently for future hackathon checkpoints.

#### Acceptance Criteria

1. THE BedrockClient module SHALL have zero imports from Datadog libraries
2. THE Observability module SHALL have zero imports from CLI or IO modules
3. THE CLI module SHALL orchestrate the flow: load config, enable observability, invoke traced LLM call, print output, and flush spans
