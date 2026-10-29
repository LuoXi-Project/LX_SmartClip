"""MCP 测试服务器（仅供 test_agent_mcp.py 使用）：stdio 传输，暴露 add 工具。"""

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("test-tools")


@mcp.tool(description="Add two integers and return the sum.")
def add(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    mcp.run()
