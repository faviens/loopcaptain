# Upstream issues

Behaviour of external tools this repository works around. Filing upstream
is a public post and needs the person's yes.

| # | Upstream | Behaviour | Workaround | Report |
|---|---|---|---|---|
| U1 | `mcp` Python SDK 2.x | `FastMCP` was renamed to `MCPServer` (`mcp.server.mcpserver`); code written for 1.x fails on import | `pyproject.toml` requires `mcp>=2.0` and `mcp_server/server.py` imports `MCPServer` | none needed: documented in the SDK's migration guide |
