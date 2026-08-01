"""Expose the guarded NL2SQL workflow as an MCP server."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict

from vanna.agents.nl2sql import SQLValidatorAgent
from vanna.services import SchemaRetriever


class Nl2SqlMcpService:
    """Transport-independent implementations behind the MCP tools."""

    def __init__(
        self,
        workflow_factory: Callable[[], Any],
        schema_repository: Any,
        executor: Any,
    ):
        self.workflow_factory = workflow_factory
        self.schema_repository = schema_repository
        self.executor = executor
        self.validator = SQLValidatorAgent()

    async def retrieve_schema(self, question: str, top_k: int = 5) -> Dict[str, Any]:
        if not question.strip():
            raise ValueError("question must not be empty")
        if not 1 <= top_k <= 50:
            raise ValueError("top_k must be between 1 and 50")
        catalog = await asyncio.to_thread(self.schema_repository.load)
        context = SchemaRetriever(catalog).retrieve(question, top_k=top_k)
        return context.model_dump(mode="json")

    async def validate_sql(self, sql: str) -> Dict[str, Any]:
        catalog = await asyncio.to_thread(self.schema_repository.load)
        return self.validator.validate(sql, catalog).model_dump(mode="json")

    async def execute_sql(self, sql: str) -> Dict[str, Any]:
        """Execute SQL only after deterministic validation against the full catalog."""
        catalog = await asyncio.to_thread(self.schema_repository.load)
        validation = self.validator.validate(sql, catalog)
        if not validation.valid:
            return {
                "success": False,
                "error": validation.reason or "SQL validation failed",
                "validation": validation.model_dump(mode="json"),
            }
        result = await self.executor.run(sql)
        payload = result.model_dump(mode="json")
        payload["validation"] = validation.model_dump(mode="json")
        return payload

    async def analyze_question(
        self, question: str, conversation_context: str = ""
    ) -> Dict[str, Any]:
        if not question.strip():
            raise ValueError("question must not be empty")
        result = await self.workflow_factory().run(
            question,
            conversation_context=conversation_context or None,
        )
        return result.model_dump(mode="json")


def create_nl2sql_mcp_server(
    workflow_factory: Callable[[], Any],
    schema_repository: Any,
    executor: Any,
    *,
    name: str = "Vanna NL2SQL",
    host: str = "127.0.0.1",
    port: int = 8001,
) -> Any:
    """Create a FastMCP server without making MCP a base dependency."""
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            'MCP support requires Python 3.10+ and `pip install -e ".[mcp]"`'
        ) from exc

    service = Nl2SqlMcpService(workflow_factory, schema_repository, executor)
    mcp = FastMCP(
        name,
        instructions=(
            "Retrieve database schema, validate read-only MySQL, execute validated "
            "queries, or run the complete NL2SQL analysis workflow."
        ),
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False)

    @mcp.tool(annotations=read_only)
    async def retrieve_schema(question: str, top_k: int = 5) -> Dict[str, Any]:
        """Retrieve tables and columns relevant to a natural-language question."""
        return await service.retrieve_schema(question, top_k)

    @mcp.tool(annotations=read_only)
    async def validate_sql(sql: str) -> Dict[str, Any]:
        """Validate that one MySQL query is read-only and uses known schema."""
        return await service.validate_sql(sql)

    @mcp.tool(annotations=read_only)
    async def execute_sql(sql: str) -> Dict[str, Any]:
        """Validate and execute one bounded, read-only MySQL SELECT query."""
        return await service.execute_sql(sql)

    @mcp.tool(annotations=read_only)
    async def analyze_question(
        question: str, conversation_context: str = ""
    ) -> Dict[str, Any]:
        """Run planning, schema retrieval, SQL generation, execution and analysis."""
        return await service.analyze_question(question, conversation_context)

    return mcp
