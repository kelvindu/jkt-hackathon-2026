"""
Bedrock Client Module

This module provides the BedrockClient class for interacting with AWS Bedrock's
converse API using the amazon.nova-micro-v1:0 model.

Validates Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
"""

import os
from dataclasses import dataclass
from typing import Any, Optional
import boto3
from botocore.exceptions import ClientError, BotoCoreError


@dataclass
class ToolUse:
    """
    Represents a tool use request from Bedrock.
    
    Attributes:
        tool_use_id: Unique identifier for the tool use
        name: Name of the tool to be called
        input: Dictionary of arguments for the tool
    """
    tool_use_id: str
    name: str
    input: dict[str, Any]


@dataclass
class BedrockResponse:
    """
    Represents a response from the Bedrock converse API.
    
    Attributes:
        message: The complete message content from the response
        stop_reason: Reason for conversation stop (e.g., "end_turn", "tool_use")
        usage: Token usage statistics (inputTokens, outputTokens, totalTokens)
        tool_uses: List of tool use requests extracted from the response
    """
    message: dict[str, Any]
    stop_reason: str
    usage: dict[str, int]
    tool_uses: list[ToolUse]


class BedrockAuthError(Exception):
    """Raised when AWS Bedrock authentication fails."""
    pass


class BedrockResponseError(Exception):
    """Raised when Bedrock returns an invalid or unexpected response."""
    pass


class BedrockClient:
    """
    Client for interacting with AWS Bedrock's converse API.
    
    This client uses boto3 to communicate with AWS Bedrock, targeting the
    amazon.nova-micro-v1:0 model for cost-effective conversational AI.
    
    Authentication is handled via AWS credentials from the environment:
    - AWS_ACCESS_KEY_ID
    - AWS_SECRET_ACCESS_KEY
    - AWS_REGION (defaults to us-east-1)
    """
    
    def __init__(self, model_id: str = "amazon.nova-micro-v1:0"):
        """
        Initialize the Bedrock client.
        
        Args:
            model_id: The Bedrock model identifier (default: amazon.nova-micro-v1:0)
            
        Raises:
            BedrockAuthError: If AWS credentials are not properly configured
        """
        self.model_id = model_id
        self.region = os.getenv("AWS_REGION", "us-east-1")
        
        try:
            # Initialize boto3 bedrock-runtime client
            # Authentication uses AWS credentials from environment
            self.client = boto3.client(
                "bedrock-runtime",
                region_name=self.region
            )
        except (ClientError, BotoCoreError) as e:
            raise BedrockAuthError(
                f"Failed to initialize Bedrock client: {str(e)}"
            ) from e
    
    def converse(
        self,
        messages: list[dict[str, Any]],
        tool_config: Optional[dict[str, Any]] = None,
        system: Optional[str] = None,
    ) -> BedrockResponse:
        """
        Send a conversation turn to Bedrock using the converse() API.

        Args:
            messages: List of message dictionaries in Bedrock format.
            tool_config: Optional Bedrock toolConfig dict advertising available tools.
                         Format: {"tools": [{"toolSpec": {...}}, ...]}
            system: Optional system prompt string. Sent as the first system turn.

        Returns:
            BedrockResponse object containing the response data and extracted tool uses.

        Raises:
            BedrockAuthError: If authentication fails during the API call.
            BedrockResponseError: If the response format is invalid.

        Example:
            >>> messages = [{"role": "user", "content": [{"text": "Hello"}]}]
            >>> response = client.converse(messages)
            >>> print(response.stop_reason)
        """
        try:
            kwargs: dict[str, Any] = {
                "modelId": self.model_id,
                "messages": messages,
            }
            if tool_config:
                kwargs["toolConfig"] = tool_config
            if system:
                kwargs["system"] = [{"text": system}]

            # Call Bedrock converse() API
            response = self.client.converse(**kwargs)
            
            # Validate response structure
            if "output" not in response or "message" not in response["output"]:
                raise BedrockResponseError(
                    "Invalid response structure: missing 'output.message'"
                )
            
            message = response["output"]["message"]
            stop_reason = response.get("stopReason", "unknown")
            usage = response.get("usage", {
                "inputTokens": 0,
                "outputTokens": 0,
                "totalTokens": 0
            })
            
            # Extract tool uses from the response
            tool_uses = self.extract_tool_uses(response)
            
            return BedrockResponse(
                message=message,
                stop_reason=stop_reason,
                usage=usage,
                tool_uses=tool_uses
            )
            
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            if error_code in ["UnrecognizedClientException", "InvalidSignatureException"]:
                raise BedrockAuthError(
                    f"AWS authentication failed: {str(e)}"
                ) from e
            raise BedrockResponseError(
                f"Bedrock API error ({error_code}): {str(e)}"
            ) from e
        except (BotoCoreError, KeyError) as e:
            raise BedrockResponseError(
                f"Failed to process Bedrock response: {str(e)}"
            ) from e
    
    def format_message(
        self,
        role: str,
        content: Any
    ) -> dict[str, Any]:
        """
        Format a message for the Bedrock converse API.
        
        This method creates messages in Bedrock's expected format. Content can be:
        - A string (converted to text content)
        - A list of content blocks (used as-is)
        - A dictionary (wrapped in a list)
        
        Args:
            role: Message role ("user" or "assistant")
            content: Message content (string, list, or dict)
            
        Returns:
            Dictionary in Bedrock message format
            
        Example:
            >>> msg = client.format_message("user", "Hello")
            >>> print(msg)
            {'role': 'user', 'content': [{'text': 'Hello'}]}
        """
        # Validate role
        if role not in ["user", "assistant"]:
            raise ValueError(f"Invalid role: {role}. Must be 'user' or 'assistant'")
        
        # Format content based on type
        if isinstance(content, str):
            # String content: wrap in text block
            formatted_content = [{"text": content}]
        elif isinstance(content, list):
            # Already a list of content blocks
            formatted_content = content
        elif isinstance(content, dict):
            # Single content block: wrap in list
            formatted_content = [content]
        else:
            raise ValueError(
                f"Invalid content type: {type(content)}. "
                "Must be str, list, or dict"
            )
        
        return {
            "role": role,
            "content": formatted_content
        }
    
    def extract_tool_uses(self, response: dict[str, Any]) -> list[ToolUse]:
        """
        Extract tool use requests from a Bedrock response.
        
        This method parses the response for toolUse content blocks and extracts
        the tool name, arguments, and tool use ID for routing to MCP.
        
        Args:
            response: Raw response dictionary from Bedrock converse() API
            
        Returns:
            List of ToolUse objects, empty if no tool uses found
            
        Example:
            >>> response = {...}  # Response with toolUse blocks
            >>> tool_uses = client.extract_tool_uses(response)
            >>> for tool in tool_uses:
            ...     print(f"Tool: {tool.name}, Args: {tool.input}")
        """
        tool_uses = []
        
        try:
            # Navigate to message content
            message = response.get("output", {}).get("message", {})
            content_blocks = message.get("content", [])
            
            # Iterate through content blocks looking for toolUse
            for block in content_blocks:
                if "toolUse" in block:
                    tool_use_data = block["toolUse"]
                    
                    # Extract required fields
                    tool_use_id = tool_use_data.get("toolUseId", "")
                    name = tool_use_data.get("name", "")
                    tool_input = tool_use_data.get("input", {})
                    
                    # Validate required fields are present
                    if tool_use_id and name:
                        tool_uses.append(ToolUse(
                            tool_use_id=tool_use_id,
                            name=name,
                            input=tool_input
                        ))
        except (KeyError, TypeError) as e:
            # Log the error but don't fail - return empty list
            # This allows graceful handling of malformed responses
            pass
        
        return tool_uses
