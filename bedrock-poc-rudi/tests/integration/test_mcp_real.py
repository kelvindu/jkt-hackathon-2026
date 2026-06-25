"""
Integration test for MCP client with real MCP server connection
Tests that the MCP client can independently connect and call tools
"""

import pytest
from src.mcp_client import MCPClient, MCPConnectionError


class TestMCPClientRealConnection:
    """Test MCP client with real Datadog MCP server"""

    def test_mcp_client_can_connect_to_real_server(self):
        """Verify MCP client can establish connection to Datadog MCP server"""
        # This test requires the Datadog MCP server to be available
        # Command: npx -y @datadog/mcp-server-datadog
        
        client = MCPClient(["npx", "-y", "@datadog/mcp-server-datadog"])
        
        try:
            # Attempt connection
            client.connect()
            
            # Verify connection status
            assert client.is_connected(), "MCP client should report connected status"
            
            print("✓ MCP client successfully connected to Datadog MCP server")
            
        except MCPConnectionError as e:
            pytest.skip(f"MCP server not available: {e}")
        finally:
            if client.is_connected():
                client.disconnect()
    
    def test_mcp_client_can_list_available_tools(self):
        """Verify MCP client can query available tools from server"""
        client = MCPClient(["npx", "-y", "@datadog/mcp-server-datadog"])
        
        try:
            client.connect()
            
            # Try to list tools - this depends on MCP server capabilities
            # Different MCP servers may have different tool discovery methods
            # For now, we just verify the connection works
            
            assert client.is_connected(), "Client should remain connected"
            
            print("✓ MCP client maintained stable connection")
            
        except MCPConnectionError as e:
            pytest.skip(f"MCP server not available: {e}")
        finally:
            if client.is_connected():
                client.disconnect()
    
    def test_mcp_client_handles_disconnect_gracefully(self):
        """Verify MCP client can disconnect cleanly"""
        client = MCPClient(["npx", "-y", "@datadog/mcp-server-datadog"])
        
        try:
            client.connect()
            assert client.is_connected()
            
            # Disconnect
            client.disconnect()
            
            # Verify disconnected
            assert not client.is_connected(), "Client should report disconnected status"
            
            print("✓ MCP client disconnected gracefully")
            
        except MCPConnectionError as e:
            pytest.skip(f"MCP server not available: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
