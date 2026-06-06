"""AlignOS MCP server package.

`mcp_server.core` holds the pure tool implementations (no MCP transport), so the
FastAPI backend can call them directly as a local fallback. `mcp_server.server`
wraps them as an MCP stdio server.
"""
