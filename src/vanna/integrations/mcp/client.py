"""MCP client transports and adapters for Vanna tools."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Literal, Optional, Type

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from vanna.core.tool import Tool, ToolContext, ToolResult, ToolSchema


class McpDependencyError(ImportError):
    """Raised when an MCP connection is attempted without the optional SDK."""


class McpConnectionConfig(BaseModel):
    """Connection settings for one remote MCP server."""

    name: str = Field(min_length=1)
    transport: Literal["streamable-http", "stdio"]
    url: Optional[str] = None
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    cwd: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    tool_name_prefix: str = ""
    request_timeout_seconds: float = Field(default=30.0, gt=0)
    read_timeout_seconds: float = Field(default=300.0, gt=0)

    @model_validator(mode="after")
    def validate_transport_settings(self) -> "McpConnectionConfig":
        if self.transport == "streamable-http" and not self.url:
            raise ValueError("url is required for streamable-http transport")
        if self.transport == "stdio" and not self.command:
            raise ValueError("command is required for stdio transport")
        return self


class McpToolArguments(BaseModel):
    """Permissive argument container; MCP's JSON Schema remains authoritative."""

    model_config = ConfigDict(extra="allow")


class McpClient:
    """MCP client supporting stdio and Streamable HTTP transports."""

    def __init__(self, config: McpConnectionConfig):
        self.config = config

    @staticmethod
    def _sdk() -> tuple[Any, Any, Any, Any]:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise McpDependencyError(
                'MCP support requires Python 3.10+ and `pip install -e ".[mcp]"`'
            ) from exc
        return (
            ClientSession,
            StdioServerParameters,
            stdio_client,
            streamable_http_client,
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[Any]:
        ClientSession, StdioServerParameters, stdio_client, http_client = self._sdk()
        if self.config.transport == "stdio":
            assert self.config.command is not None
            parameters = StdioServerParameters(
                command=self.config.command,
                args=self.config.args,
                env=self.config.env or None,
                cwd=self.config.cwd,
            )
            async with stdio_client(parameters) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session
            return

        timeout = httpx.Timeout(
            self.config.request_timeout_seconds,
            read=self.config.read_timeout_seconds,
        )
        assert self.config.url is not None
        async with httpx.AsyncClient(
            headers=self.config.headers, timeout=timeout
        ) as transport_client:
            async with http_client(
                self.config.url, http_client=transport_client
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session

    async def list_tools(self) -> List[Dict[str, Any]]:
        async with self.session() as session:
            response = await session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            for tool in response.tools
        ]

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        async with self.session() as session:
            result = await session.call_tool(name, arguments=arguments)
        content = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else str(item)
            for item in result.content
        ]
        return {
            "is_error": bool(getattr(result, "isError", False)),
            "structured_content": getattr(result, "structuredContent", None),
            "content": content,
        }

    async def discover_tools(self) -> List["McpRemoteTool"]:
        return [
            McpRemoteTool(self, descriptor) for descriptor in await self.list_tools()
        ]


class McpRemoteTool(Tool[McpToolArguments]):
    """Expose a discovered remote MCP tool through Vanna's Tool interface."""

    def __init__(self, client: McpClient, descriptor: Dict[str, Any]):
        self.client = client
        self.remote_name = str(descriptor["name"])
        self._description = str(descriptor.get("description") or "")
        self.input_schema = dict(descriptor.get("input_schema") or {})

    @property
    def name(self) -> str:
        return f"{self.client.config.tool_name_prefix}{self.remote_name}"

    @property
    def description(self) -> str:
        return self._description

    def get_args_schema(self) -> Type[McpToolArguments]:
        return McpToolArguments

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters=self.input_schema,
            access_groups=self.access_groups,
        )

    async def execute(
        self, context: ToolContext, args: McpToolArguments
    ) -> ToolResult:
        del context
        try:
            payload = await self.client.call_tool(
                self.remote_name, args.model_dump(mode="json", exclude_none=True)
            )
            preferred = payload.get("structured_content")
            if preferred is None:
                preferred = payload.get("content", [])
            result_text = json.dumps(preferred, ensure_ascii=False, default=str)
            is_error = bool(payload.get("is_error"))
            return ToolResult(
                success=not is_error,
                result_for_llm=result_text,
                error=result_text if is_error else None,
                metadata={"mcp_server": self.client.config.name, **payload},
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                result_for_llm=f"MCP tool call failed: {exc}",
                error=str(exc),
                metadata={"mcp_server": self.client.config.name},
            )
