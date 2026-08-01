"""Discover and call tools from a remote Streamable HTTP MCP server."""

import argparse
import asyncio
import json
from typing import Optional

from vanna.integrations.mcp import McpClient, McpConnectionConfig


async def run(url: str, tool_name: Optional[str], arguments: str) -> None:
    client = McpClient(
        McpConnectionConfig(
            name="nl2sql",
            transport="streamable-http",
            url=url,
        )
    )
    if not tool_name:
        print(json.dumps(await client.list_tools(), ensure_ascii=False, indent=2))
        return
    result = await client.call_tool(tool_name, json.loads(arguments))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8001/mcp")
    parser.add_argument("--tool")
    parser.add_argument("--arguments", default="{}")
    args = parser.parse_args()
    asyncio.run(run(args.url, args.tool, args.arguments))


if __name__ == "__main__":
    main()
