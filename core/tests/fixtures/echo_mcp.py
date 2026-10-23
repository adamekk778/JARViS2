"""Tiny MCP server used by tests (stdio)."""
try:
    from mcp.server.mcpserver import MCPServer as Server  # mcp >= 2
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as Server

server = Server("echo")


@server.tool()
def add(a: int, b: int) -> str:
    """Sečte dvě čísla."""
    return str(a + b)


@server.tool()
def delete_everything(confirm: bool = False) -> str:
    """Nebezpečná ukázka."""
    return "nic se nesmazalo"


if __name__ == "__main__":
    server.run()
