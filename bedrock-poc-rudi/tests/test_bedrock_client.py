"""
Unit tests for BedrockClient

Tests the Bedrock client functionality with mocked boto3 responses.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from botocore.exceptions import ClientError

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.bedrock_client import (
    BedrockClient,
    BedrockResponse,
    ToolUse,
    BedrockAuthError,
    BedrockResponseError
)


class TestBedrockClientInitialization:
    """Test BedrockClient initialization and authentication."""
    
    @patch('src.bedrock_client.boto3.client')
    def test_init_with_default_model(self, mock_boto_client):
        """Test initialization with default model ID."""
        mock_client = Mock()
        mock_boto_client.return_value = mock_client
        
        client = BedrockClient()
        
        assert client.model_id == "amazon.nova-micro-v1:0"
        mock_boto_client.assert_called_once_with(
            "bedrock-runtime",
            region_name="us-east-1"
        )
    
    @patch('src.bedrock_client.boto3.client')
    def test_init_with_custom_model(self, mock_boto_client):
        """Test initialization with custom model ID."""
        mock_client = Mock()
        mock_boto_client.return_value = mock_client
        
        client = BedrockClient(model_id="custom-model-v1")
        
        assert client.model_id == "custom-model-v1"
    
    @patch.dict(os.environ, {"AWS_REGION": "us-west-2"})
    @patch('src.bedrock_client.boto3.client')
    def test_init_with_custom_region(self, mock_boto_client):
        """Test initialization respects AWS_REGION environment variable."""
        mock_client = Mock()
        mock_boto_client.return_value = mock_client
        
        client = BedrockClient()
        
        assert client.region == "us-west-2"
        mock_boto_client.assert_called_once_with(
            "bedrock-runtime",
            region_name="us-west-2"
        )
    
    @patch('src.bedrock_client.boto3.client')
    def test_init_authentication_failure(self, mock_boto_client):
        """Test initialization raises BedrockAuthError on AWS auth failure."""
        mock_boto_client.side_effect = ClientError(
            {"Error": {"Code": "InvalidClientTokenId", "Message": "Invalid token"}},
            "bedrock-runtime"
        )
        
        with pytest.raises(BedrockAuthError):
            BedrockClient()


class TestBedrockClientConverse:
    """Test BedrockClient converse method."""
    
    @patch('src.bedrock_client.boto3.client')
    def test_converse_success_with_text_response(self, mock_boto_client):
        """Test successful converse call with text response."""
        mock_client = Mock()
        mock_boto_client.return_value = mock_client
        
        # Mock Bedrock API response
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "Hello, how can I help?"}]
                }
            },
            "stopReason": "end_turn",
            "usage": {
                "inputTokens": 10,
                "outputTokens": 15,
                "totalTokens": 25
            }
        }
        
        client = BedrockClient()
        messages = [{"role": "user", "content": [{"text": "Hello"}]}]
        response = client.converse(messages)
        
        assert isinstance(response, BedrockResponse)
        assert response.stop_reason == "end_turn"
        assert response.usage["inputTokens"] == 10
        assert response.usage["outputTokens"] == 15
        assert len(response.tool_uses) == 0
        mock_client.converse.assert_called_once_with(
            modelId="amazon.nova-micro-v1:0",
            messages=messages
        )
    
    @patch('src.bedrock_client.boto3.client')
    def test_converse_with_tool_use(self, mock_boto_client):
        """Test converse call that returns tool use requests."""
        mock_client = Mock()
        mock_boto_client.return_value = mock_client
        
        # Mock Bedrock API response with toolUse
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"text": "I'll query the logs."},
                        {
                            "toolUse": {
                                "toolUseId": "abc123",
                                "name": "datadog_query_logs",
                                "input": {
                                    "query": "service:api status:error",
                                    "from": "2024-01-15T14:00:00Z"
                                }
                            }
                        }
                    ]
                }
            },
            "stopReason": "tool_use",
            "usage": {
                "inputTokens": 50,
                "outputTokens": 30,
                "totalTokens": 80
            }
        }
        
        client = BedrockClient()
        messages = [{"role": "user", "content": [{"text": "Check errors"}]}]
        response = client.converse(messages)
        
        assert response.stop_reason == "tool_use"
        assert len(response.tool_uses) == 1
        assert response.tool_uses[0].tool_use_id == "abc123"
        assert response.tool_uses[0].name == "datadog_query_logs"
        assert response.tool_uses[0].input["query"] == "service:api status:error"
    
    @patch('src.bedrock_client.boto3.client')
    def test_converse_invalid_response_structure(self, mock_boto_client):
        """Test converse raises error on invalid response structure."""
        mock_client = Mock()
        mock_boto_client.return_value = mock_client
        
        # Mock invalid response (missing output.message)
        mock_client.converse.return_value = {
            "output": {}
        }
        
        client = BedrockClient()
        messages = [{"role": "user", "content": [{"text": "Hello"}]}]
        
        with pytest.raises(BedrockResponseError, match="missing 'output.message'"):
            client.converse(messages)
    
    @patch('src.bedrock_client.boto3.client')
    def test_converse_authentication_error(self, mock_boto_client):
        """Test converse raises BedrockAuthError on auth failure."""
        mock_client = Mock()
        mock_boto_client.return_value = mock_client
        
        mock_client.converse.side_effect = ClientError(
            {"Error": {"Code": "UnrecognizedClientException", "Message": "Auth failed"}},
            "converse"
        )
        
        client = BedrockClient()
        messages = [{"role": "user", "content": [{"text": "Hello"}]}]
        
        with pytest.raises(BedrockAuthError):
            client.converse(messages)


class TestFormatMessage:
    """Test message formatting for Bedrock API."""
    
    @patch('src.bedrock_client.boto3.client')
    def test_format_message_string_content(self, mock_boto_client):
        """Test formatting message with string content."""
        mock_boto_client.return_value = Mock()
        client = BedrockClient()
        
        message = client.format_message("user", "Hello, world!")
        
        assert message["role"] == "user"
        assert message["content"] == [{"text": "Hello, world!"}]
    
    @patch('src.bedrock_client.boto3.client')
    def test_format_message_list_content(self, mock_boto_client):
        """Test formatting message with list content."""
        mock_boto_client.return_value = Mock()
        client = BedrockClient()
        
        content = [
            {"text": "Part 1"},
            {"text": "Part 2"}
        ]
        message = client.format_message("assistant", content)
        
        assert message["role"] == "assistant"
        assert message["content"] == content
    
    @patch('src.bedrock_client.boto3.client')
    def test_format_message_dict_content(self, mock_boto_client):
        """Test formatting message with dict content."""
        mock_boto_client.return_value = Mock()
        client = BedrockClient()
        
        content = {"text": "Single block"}
        message = client.format_message("user", content)
        
        assert message["role"] == "user"
        assert message["content"] == [content]
    
    @patch('src.bedrock_client.boto3.client')
    def test_format_message_invalid_role(self, mock_boto_client):
        """Test formatting message with invalid role raises ValueError."""
        mock_boto_client.return_value = Mock()
        client = BedrockClient()
        
        with pytest.raises(ValueError, match="Invalid role"):
            client.format_message("invalid", "content")
    
    @patch('src.bedrock_client.boto3.client')
    def test_format_message_invalid_content_type(self, mock_boto_client):
        """Test formatting message with invalid content type raises ValueError."""
        mock_boto_client.return_value = Mock()
        client = BedrockClient()
        
        with pytest.raises(ValueError, match="Invalid content type"):
            client.format_message("user", 123)


class TestExtractToolUses:
    """Test tool use extraction from Bedrock responses."""
    
    @patch('src.bedrock_client.boto3.client')
    def test_extract_single_tool_use(self, mock_boto_client):
        """Test extracting a single tool use from response."""
        mock_boto_client.return_value = Mock()
        client = BedrockClient()
        
        response = {
            "output": {
                "message": {
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "tool-1",
                                "name": "query_logs",
                                "input": {"query": "error"}
                            }
                        }
                    ]
                }
            }
        }
        
        tool_uses = client.extract_tool_uses(response)
        
        assert len(tool_uses) == 1
        assert tool_uses[0].tool_use_id == "tool-1"
        assert tool_uses[0].name == "query_logs"
        assert tool_uses[0].input == {"query": "error"}
    
    @patch('src.bedrock_client.boto3.client')
    def test_extract_multiple_tool_uses(self, mock_boto_client):
        """Test extracting multiple tool uses from response."""
        mock_boto_client.return_value = Mock()
        client = BedrockClient()
        
        response = {
            "output": {
                "message": {
                    "content": [
                        {"text": "Investigating..."},
                        {
                            "toolUse": {
                                "toolUseId": "tool-1",
                                "name": "query_logs",
                                "input": {"query": "error"}
                            }
                        },
                        {
                            "toolUse": {
                                "toolUseId": "tool-2",
                                "name": "query_metrics",
                                "input": {"metric": "error_rate"}
                            }
                        }
                    ]
                }
            }
        }
        
        tool_uses = client.extract_tool_uses(response)
        
        assert len(tool_uses) == 2
        assert tool_uses[0].name == "query_logs"
        assert tool_uses[1].name == "query_metrics"
    
    @patch('src.bedrock_client.boto3.client')
    def test_extract_no_tool_uses(self, mock_boto_client):
        """Test extracting tool uses from response with none present."""
        mock_boto_client.return_value = Mock()
        client = BedrockClient()
        
        response = {
            "output": {
                "message": {
                    "content": [
                        {"text": "Here is the answer."}
                    ]
                }
            }
        }
        
        tool_uses = client.extract_tool_uses(response)
        
        assert len(tool_uses) == 0
    
    @patch('src.bedrock_client.boto3.client')
    def test_extract_tool_uses_malformed_response(self, mock_boto_client):
        """Test extracting tool uses handles malformed response gracefully."""
        mock_boto_client.return_value = Mock()
        client = BedrockClient()
        
        # Malformed response (missing expected structure)
        response = {
            "output": {}
        }
        
        tool_uses = client.extract_tool_uses(response)
        
        # Should return empty list, not raise error
        assert len(tool_uses) == 0
    
    @patch('src.bedrock_client.boto3.client')
    def test_extract_tool_uses_missing_required_fields(self, mock_boto_client):
        """Test extracting tool uses skips entries with missing required fields."""
        mock_boto_client.return_value = Mock()
        client = BedrockClient()
        
        response = {
            "output": {
                "message": {
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "tool-1",
                                # Missing 'name' field
                                "input": {"query": "error"}
                            }
                        },
                        {
                            "toolUse": {
                                "toolUseId": "tool-2",
                                "name": "valid_tool",
                                "input": {}
                            }
                        }
                    ]
                }
            }
        }
        
        tool_uses = client.extract_tool_uses(response)
        
        # Should only extract the valid tool use
        assert len(tool_uses) == 1
        assert tool_uses[0].name == "valid_tool"


class TestDataclasses:
    """Test dataclass structures."""
    
    def test_tool_use_dataclass(self):
        """Test ToolUse dataclass creation."""
        tool = ToolUse(
            tool_use_id="abc123",
            name="test_tool",
            input={"arg1": "value1"}
        )
        
        assert tool.tool_use_id == "abc123"
        assert tool.name == "test_tool"
        assert tool.input["arg1"] == "value1"
    
    def test_bedrock_response_dataclass(self):
        """Test BedrockResponse dataclass creation."""
        response = BedrockResponse(
            message={"role": "assistant", "content": []},
            stop_reason="end_turn",
            usage={"inputTokens": 10, "outputTokens": 20, "totalTokens": 30},
            tool_uses=[]
        )
        
        assert response.stop_reason == "end_turn"
        assert response.usage["totalTokens"] == 30
        assert len(response.tool_uses) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
