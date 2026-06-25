"""
MCP Client Integration Module

This module provides the MCPClient class for connecting to and communicating
with MCP (Model Context Protocol) servers, specifically for Datadog tools.

Responsibilities:
- Connect to MCP server process
- Send tool call requests
- Parse tool call responses
- Handle connection and execution errors

Requirements: 2.1, 2.3, 2.5
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


@dataclass
class MCPToolResponse:
    """
    Response from an MCP tool call.
    
    Attributes:
        success: Whether the tool call succeeded
        result: The result data from the tool call (if successful)
        error: Error message (if failed)
    """
    success: bool
    result: Any = None
    error: Optional[str] = None


class MCPConnectionError(Exception):
    """Raised when MCP server connection fails."""
    pass


class MCPClient:
    """
    Client for communicating with MCP servers.
    
    This client manages the connection lifecycle and routes tool calls
    to the MCP server, handling errors gracefully.
    
    Requirements:
    - 2.1: Integrate Python MCP client library
    - 2.3: Route tool requests to MCP server
    - 2.5: Handle MCP server connection errors
    """
    
    def __init__(self, server_command: list[str]):
        """
        Initialize the MCP client.
        
        Args:
            server_command: Command list to start the MCP server process
                          e.g., ["npx", "-y", "@datadog/mcp-server-datadog"]
        
        Requirement 2.1: Initialize MCP client with server command
        """
        self.server_command = server_command
        self._session: Optional[ClientSession] = None
        self._client_context = None
        self._read_stream = None
        self._write_stream = None
        logger.debug(f"MCPClient initialized with command: {server_command}")
    
    def connect(self) -> None:
        """
        Establish connection to the MCP server.
        
        Raises:
            MCPConnectionError: If connection fails
        
        Requirement 2.1: Connect to MCP server process
        Requirement 2.5: Handle connection errors by raising MCPConnectionError
        """
        if self._session is not None:
            logger.warning("MCP client already connected")
            return
        
        try:
            logger.info(f"Connecting to MCP server: {' '.join(self.server_command)}")
            
            # Create server parameters
            server_params = StdioServerParameters(
                command=self.server_command[0],
                args=self.server_command[1:] if len(self.server_command) > 1 else [],
                env=None
            )
            
            # Store the context manager for later cleanup
            self._client_context = stdio_client(server_params)
            self._read_stream, self._write_stream = self._client_context.__enter__()
            
            # Create session
            self._session = ClientSession(self._read_stream, self._write_stream)
            
            logger.info("MCP server connection established")
            
        except Exception as e:
            error_msg = f"Failed to connect to MCP server: {str(e)}"
            logger.error(error_msg)
            raise MCPConnectionError(error_msg) from e
    
    def is_connected(self) -> bool:
        """
        Check if the client is connected to the MCP server.
        
        Returns:
            True if connected, False otherwise
        
        Requirement 2.1: Provide connection status check
        """
        return self._session is not None
    
    async def call_tool(self, name: str, arguments: dict) -> MCPToolResponse:
        """
        Call a tool on the MCP server.
        
        Args:
            name: Name of the tool to call
            arguments: Dictionary of arguments for the tool
        
        Returns:
            MCPToolResponse with success status, result, or error
        
        Requirement 2.2: Extract tool name and arguments
        Requirement 2.3: Route tool request to MCP server
        Requirement 2.4: Format MCP tool responses
        """
        if not self.is_connected():
            error_msg = "MCP client is not connected"
            logger.error(error_msg)
            return MCPToolResponse(success=False, error=error_msg)
        
        try:
            logger.info(f"Calling MCP tool: {name} with arguments: {arguments}")
            
            # Call the tool through the MCP session
            result = await self._session.call_tool(name, arguments)
            
            logger.debug(f"Tool {name} executed successfully")
            return MCPToolResponse(success=True, result=result)
            
        except Exception as e:
            error_msg = f"Tool execution failed for {name}: {str(e)}"
            logger.error(error_msg)
            return MCPToolResponse(success=False, error=error_msg)
    
    def disconnect(self) -> None:
        """
        Disconnect from the MCP server and clean up resources.
        
        Requirement 2.1: Properly disconnect and cleanup MCP connection
        """
        if self._session is None:
            logger.debug("MCP client not connected, nothing to disconnect")
            return
        
        try:
            logger.info("Disconnecting from MCP server")
            
            # Close the session
            self._session = None
            
            # Exit the client context to cleanup stdio streams
            if self._client_context is not None:
                try:
                    self._client_context.__exit__(None, None, None)
                except Exception as e:
                    logger.warning(f"Error during context cleanup: {e}")
                finally:
                    self._client_context = None
                    self._read_stream = None
                    self._write_stream = None
            
            logger.info("MCP server disconnected successfully")
            
        except Exception as e:
            logger.error(f"Error during MCP disconnect: {str(e)}")
            # Ensure cleanup even if errors occur
            self._session = None
            self._client_context = None
            self._read_stream = None
            self._write_stream = None


@dataclass
class MCPToolCall:
    """
    Represents a tool call to be executed via MCP.
    
    Attributes:
        name: Name of the tool
        arguments: Dictionary of arguments for the tool call
    """
    name: str
    arguments: dict
