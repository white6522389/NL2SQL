"""Model Context Protocol server and client integration.

The official MCP SDK is optional. Install it with
``pip install -e ".[mcp]"`` before opening a real MCP connection.
"""

from .client import McpClient, McpConnectionConfig, McpRemoteTool, McpToolArguments
from .server import Nl2SqlMcpService, create_nl2sql_mcp_server

__all__ = [
    "McpClient",
    "McpConnectionConfig",
    "McpRemoteTool",
    "McpToolArguments",
    "Nl2SqlMcpService",
    "create_nl2sql_mcp_server",
]
