"""MCP server for BodySpec DEXA data."""

try:
    from .config import MCPConfig
    from .server import create_mcp_server

    __all__ = ["MCPConfig", "create_mcp_server"]
except ImportError:
    __all__ = []
