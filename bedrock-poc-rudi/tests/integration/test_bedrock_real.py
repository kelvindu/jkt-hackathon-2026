"""
Integration test for Bedrock client with real AWS Bedrock connection
Tests that the Bedrock client can independently connect and make API calls
"""

import os
import pytest
from botocore.exceptions import ClientError, NoCredentialsError
from src.bedrock_client import BedrockClient, BedrockAuthError


class TestBedrockClientRealConnection:
    """Test Bedrock client with real AWS Bedrock API"""

    def test_bedrock_client_can_initialize_with_credentials(self):
        """Verify Bedrock client can initialize with AWS credentials"""
        # Check if AWS credentials are available
        has_credentials = (
            os.getenv("AWS_ACCESS_KEY_ID") and 
            os.getenv("AWS_SECRET_ACCESS_KEY")
        )
        
        if not has_credentials:
            pytest.skip("AWS credentials not available in environment")
        
        try:
            # Initialize client
            client = BedrockClient()
            
            # Verify client was created
            assert client is not None, "Bedrock client should be created"
            assert client.model_id == "amazon.nova-micro-v1:0", "Should use default model"
            
            print("✓ Bedrock client initialized successfully with AWS credentials")
            
        except BedrockAuthError as e:
            pytest.skip(f"AWS authentication failed: {e}")
    
    def test_bedrock_client_can_format_messages(self):
        """Verify Bedrock client can format messages correctly"""
        client = BedrockClient()
        
        # Test message formatting (no API call needed)
        message = client.format_message("user", "Test message")
        
        # Verify message structure
        assert "role" in message, "Message should have role field"
        assert "content" in message, "Message should have content field"
        assert message["role"] == "user", "Role should be 'user'"
        
        # Verify content structure
        content = message["content"]
        assert isinstance(content, list), "Content should be a list"
        assert len(content) > 0, "Content should not be empty"
        assert "text" in content[0], "Content should have text field"
        
        print("✓ Bedrock client formats messages correctly")
    
    def test_bedrock_client_validates_model_id(self):
        """Verify Bedrock client accepts valid model IDs"""
        # Test with default model
        client1 = BedrockClient()
        assert client1.model_id == "amazon.nova-micro-v1:0"
        
        # Test with custom model
        client2 = BedrockClient(model_id="amazon.nova-lite-v1:0")
        assert client2.model_id == "amazon.nova-lite-v1:0"
        
        print("✓ Bedrock client handles model ID configuration")
    
    @pytest.mark.skip(reason="Requires AWS credentials and makes real API calls")
    def test_bedrock_client_can_make_simple_converse_call(self):
        """Verify Bedrock client can make a real API call (skipped by default)"""
        # This test is skipped by default to avoid API costs
        # Run with: pytest -v -s -k test_bedrock_client_can_make_simple_converse_call --run-integration
        
        has_credentials = (
            os.getenv("AWS_ACCESS_KEY_ID") and 
            os.getenv("AWS_SECRET_ACCESS_KEY")
        )
        
        if not has_credentials:
            pytest.skip("AWS credentials not available")
        
        try:
            client = BedrockClient()
            
            # Create a simple test message
            messages = [
                client.format_message("user", "Say 'test successful' and nothing else.")
            ]
            
            # Make API call
            response = client.converse(messages)
            
            # Verify response structure
            assert "output" in response, "Response should have output field"
            assert "message" in response["output"], "Output should have message field"
            
            print("✓ Bedrock client successfully made API call")
            print(f"Response: {response}")
            
        except (BedrockAuthError, ClientError) as e:
            pytest.fail(f"Bedrock API call failed: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
