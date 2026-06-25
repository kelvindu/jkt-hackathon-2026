"""
Unit tests for MCP Client module.

Tests the MCPClient class with mocked MCP server responses to ensure
proper connection handling, tool routing, and error management.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from src.mcp_client import MCPClient, MCPToolResponse, MCPConnectionError


class TestMCPClient:
    """Test suite for MCPClient class."""
    
    def test_init_accepts_server_command_list(self):
        """Test that __init__ accepts and stores server command list."""
        server_command = ["npx", "-y", "@datadog/mcp-server-datadog"]
        client = MCPClient(server_command)
        
        assert client.server_command == server_command
        assert not client.is_connected()
    
    def test_is_connected_returns_false_initially(self):
        """Test that is_connected returns False before connection."""
        client = MCPClient(["test", "command"])
        assert client.is_connected() is False
    
    @patch('src.mcp_client.stdio_client')
    @patch('src.mcp_client.ClientSession')
    def test_connect_establishes_connection(self, mock_session_class, mock_stdio_client):
        """Test that connect() successfully establishes MCP server connection."""
        # Setup mocks
        mock_context = MagicMock()
        mock_read = Mock()
        mock_write = Mock()
        mock_context.__enter__ = Mock(return_value=(mock_read, mock_write))
        mock_context.__exit__ = Mock(return_value=None)
        mock_stdio_client.return_value = mock_context
        
        mock_session = Mock()
        mock_session_class.return_value = mock_session
        
        # Test connection
        client = MCPClient(["npx", "-y", "@datadog/mcp-server-datadog"])
        client.connect()
        
        assert client.is_connected() is True
        mock_stdio_client.assert_called_once()
        mock_session_class.assert_called_once_with(mock_read, mock_write)
    
    @patch('src.mcp_client.stdio_client')
    def test_connect_raises_on_failure(self, mock_stdio_client):
        """Test that connect() raises MCPConnectionError on failure."""
        mock_stdio_client.side_effect = Exception("Connection failed")
        
        client = MCPClient(["invalid", "command"])
        
        with pytest.raises(MCPConnectionError) as exc_info:
            client.connect()
        
        assert "Failed to connect to MCP server" in str(exc_info.value)
        assert not client.is_connected()
    
    @patch('src.mcp_client.stdio_client')
    @patch('src.mcp_client.ClientSession')
    def test_connect_warns_if_already_connected(self, mock_session_class, mock_stdio_client):
        """Test that calling connect() twice logs a warning."""
        # Setup mocks
        mock_context = MagicMock()
        mock_read = Mock()
        mock_write = Mock()
        mock_context.__enter__ = Mock(return_value=(mock_read, mock_write))
        mock_context.__exit__ = Mock(return_value=None)
        mock_stdio_client.return_value = mock_context
        
        mock_session = Mock()
        mock_session_class.return_value = mock_session
        
        client = MCPClient(["test", "command"])
        client.connect()
        
        # Try to connect again
        client.connect()
        
        # Should still be connected
        assert client.is_connected() is True
    
    @pytest.mark.asyncio
    async def test_call_tool_returns_error_when_not_connected(self):
        """Test that call_tool returns error response when not connected."""
        client = MCPClient(["test", "command"])
        
        response = await client.call_tool("test_tool", {"arg": "value"})
        
        assert response.success is False
        assert "not connected" in response.error.lower()
        assert response.result is None
    
    @pytest.mark.asyncio
    @patch('src.mcp_client.stdio_client')
    @patch('src.mcp_client.ClientSession')
    async def test_call_tool_routes_to_mcp_server(self, mock_session_class, mock_stdio_client):
        """Test that call_tool correctly routes requests to MCP server."""
        # Setup mocks
        mock_context = MagicMock()
        mock_read = Mock()
        mock_write = Mock()
        mock_context.__enter__ = Mock(return_value=(mock_read, mock_write))
        mock_context.__exit__ = Mock(return_value=None)
        mock_stdio_client.return_value = mock_context
        
        mock_session = Mock()
        mock_session.call_tool = AsyncMock(return_value={"data": "test_result"})
        mock_session_class.return_value = mock_session
        
        # Connect and call tool
        client = MCPClient(["test", "command"])
        client.connect()
        
        response = await client.call_tool("datadog_query_logs", {"query": "service:test"})
        
        assert response.success is True
        assert response.result == {"data": "test_result"}
        assert response.error is None
        mock_session.call_tool.assert_called_once_with("datadog_query_logs", {"query": "service:test"})
    
    @pytest.mark.asyncio
    @patch('src.mcp_client.stdio_client')
    @patch('src.mcp_client.ClientSession')
    async def test_call_tool_handles_execution_error(self, mock_session_class, mock_stdio_client):
        """Test that call_tool handles tool execution errors gracefully."""
        # Setup mocks
        mock_context = MagicMock()
        mock_read = Mock()
        mock_write = Mock()
        mock_context.__enter__ = Mock(return_value=(mock_read, mock_write))
        mock_context.__exit__ = Mock(return_value=None)
        mock_stdio_client.return_value = mock_context
        
        mock_session = Mock()
        mock_session.call_tool = AsyncMock(side_effect=Exception("Tool execution failed"))
        mock_session_class.return_value = mock_session
        
        # Connect and call tool
        client = MCPClient(["test", "command"])
        client.connect()
        
        response = await client.call_tool("failing_tool", {})
        
        assert response.success is False
        assert "Tool execution failed" in response.error
        assert response.result is None
    
    @patch('src.mcp_client.stdio_client')
    @patch('src.mcp_client.ClientSession')
    def test_disconnect_cleans_up_resources(self, mock_session_class, mock_stdio_client):
        """Test that disconnect() properly cleans up MCP connection."""
        # Setup mocks
        mock_context = MagicMock()
        mock_read = Mock()
        mock_write = Mock()
        mock_context.__enter__ = Mock(return_value=(mock_read, mock_write))
        mock_context.__exit__ = Mock(return_value=None)
        mock_stdio_client.return_value = mock_context
        
        mock_session = Mock()
        mock_session_class.return_value = mock_session
        
        # Connect then disconnect
        client = MCPClient(["test", "command"])
        client.connect()
        assert client.is_connected() is True
        
        client.disconnect()
        
        assert client.is_connected() is False
        mock_context.__exit__.assert_called_once()
    
    def test_disconnect_handles_not_connected_gracefully(self):
        """Test that disconnect() works even when not connected."""
        client = MCPClient(["test", "command"])
        
        # Should not raise an error
        client.disconnect()
        
        assert not client.is_connected()
    
    @patch('src.mcp_client.stdio_client')
    @patch('src.mcp_client.ClientSession')
    def test_disconnect_handles_errors_gracefully(self, mock_session_class, mock_stdio_client):
        """Test that disconnect() handles cleanup errors gracefully."""
        # Setup mocks
        mock_context = MagicMock()
        mock_read = Mock()
        mock_write = Mock()
        mock_context.__enter__ = Mock(return_value=(mock_read, mock_write))
        mock_context.__exit__ = Mock(side_effect=Exception("Cleanup error"))
        mock_stdio_client.return_value = mock_context
        
        mock_session = Mock()
        mock_session_class.return_value = mock_session
        
        # Connect then disconnect with error
        client = MCPClient(["test", "command"])
        client.connect()
        
        # Should not raise, but should cleanup
        client.disconnect()
        
        assert not client.is_connected()


class TestMCPToolResponse:
    """Test suite for MCPToolResponse dataclass."""
    
    def test_successful_response(self):
        """Test creating a successful tool response."""
        response = MCPToolResponse(
            success=True,
            result={"logs": ["log1", "log2"]},
            error=None
        )
        
        assert response.success is True
        assert response.result == {"logs": ["log1", "log2"]}
        assert response.error is None
    
    def test_error_response(self):
        """Test creating an error tool response."""
        response = MCPToolResponse(
            success=False,
            result=None,
            error="Connection timeout"
        )
        
        assert response.success is False
        assert response.result is None
        assert response.error == "Connection timeout"
    
    def test_default_values(self):
        """Test that result and error default to None."""
        response = MCPToolResponse(success=True)
        
        assert response.success is True
        assert response.result is None
        assert response.error is None


class TestMCPConnectionError:
    """Test suite for MCPConnectionError exception."""
    
    def test_can_raise_and_catch(self):
        """Test that MCPConnectionError can be raised and caught."""
        with pytest.raises(MCPConnectionError) as exc_info:
            raise MCPConnectionError("Test error")
        
        assert "Test error" in str(exc_info.value)
    
    def test_inherits_from_exception(self):
        """Test that MCPConnectionError inherits from Exception."""
        error = MCPConnectionError("Test")
        assert isinstance(error, Exception)
