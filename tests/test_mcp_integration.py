import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from vanna.agents.nl2sql import (
    ExecutionResult,
    SchemaCatalog,
    SchemaColumn,
    SchemaTable,
)
from vanna.integrations.mcp import (
    McpConnectionConfig,
    McpRemoteTool,
    McpToolArguments,
    Nl2SqlMcpService,
)


def catalog():
    return SchemaCatalog(
        database="analytics",
        tables=[SchemaTable(
            name="orders",
            comment="销售订单",
            columns=[
                SchemaColumn(name="id", data_type="bigint", key="PRI"),
                SchemaColumn(name="amount", data_type="decimal", comment="销售额"),
            ],
        )],
    )


class FakeRepository:
    def load(self):
        return catalog()


class FakeExecutor:
    def __init__(self):
        self.calls = []

    async def run(self, sql):
        self.calls.append(sql)
        return ExecutionResult(
            success=True,
            rows=[{"amount": 10}],
            columns=["amount"],
            row_count=1,
        )


class FakeWorkflow:
    async def run(self, question, conversation_context=None):
        return SimpleNamespace(model_dump=lambda mode: {
            "success": True,
            "question": question,
            "conversation_context": conversation_context,
        })


@pytest.mark.asyncio
async def test_mcp_service_retrieves_and_validates_before_execution():
    executor = FakeExecutor()
    service = Nl2SqlMcpService(FakeWorkflow, FakeRepository(), executor)
    schema = await service.retrieve_schema("查询销售额", top_k=1)
    assert schema["tables"][0]["name"] == "orders"

    rejected = await service.execute_sql("DELETE FROM orders")
    assert rejected["success"] is False
    assert executor.calls == []

    accepted = await service.execute_sql("SELECT orders.amount FROM orders")
    assert accepted["success"] is True
    assert executor.calls == ["SELECT orders.amount FROM orders"]


@pytest.mark.asyncio
async def test_mcp_service_runs_complete_workflow():
    service = Nl2SqlMcpService(FakeWorkflow, FakeRepository(), FakeExecutor())
    result = await service.analyze_question("查询销售额", "previous turn")
    assert result["conversation_context"] == "previous turn"


def test_mcp_connection_config_requires_transport_endpoint():
    with pytest.raises(ValidationError):
        McpConnectionConfig(name="remote", transport="streamable-http")
    with pytest.raises(ValidationError):
        McpConnectionConfig(name="remote", transport="stdio")


class FakeMcpClient:
    def __init__(self, response):
        self.config = SimpleNamespace(name="remote", tool_name_prefix="remote__")
        self.response = response
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.response


@pytest.mark.asyncio
async def test_remote_mcp_tool_preserves_schema_and_adapts_result():
    client = FakeMcpClient({
        "is_error": False,
        "structured_content": {"answer": 42},
        "content": [],
    })
    tool = McpRemoteTool(client, {
        "name": "calculate",
        "description": "Calculate a value",
        "input_schema": {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
        },
    })
    assert tool.name == "remote__calculate"
    assert tool.get_schema().parameters["required"] == ["value"]
    result = await tool.execute(None, McpToolArguments(value=21))
    assert result.success is True
    assert client.calls == [("calculate", {"value": 21})]
    assert '"answer": 42' in result.result_for_llm


@pytest.mark.asyncio
async def test_remote_mcp_tool_converts_remote_error():
    client = FakeMcpClient({
        "is_error": True,
        "structured_content": None,
        "content": [{"type": "text", "text": "failed"}],
    })
    tool = McpRemoteTool(
        client, {"name": "broken", "description": "", "input_schema": {}}
    )
    result = await tool.execute(None, McpToolArguments())
    assert result.success is False
    assert "failed" in result.error


@pytest.mark.asyncio
async def test_stdio_client_and_nl2sql_server_round_trip():
    pytest.importorskip("mcp")
    from vanna.integrations.mcp import McpClient

    root = Path(__file__).resolve().parents[1]
    client = McpClient(McpConnectionConfig(
        name="nl2sql-test",
        transport="stdio",
        command=sys.executable,
        args=[str(root / "tests" / "fixtures" / "mcp_nl2sql_server.py")],
        cwd=str(root),
    ))

    tools = await client.list_tools()
    assert {tool["name"] for tool in tools} == {
        "analyze_question",
        "execute_sql",
        "retrieve_schema",
        "validate_sql",
    }
    result = await client.call_tool(
        "retrieve_schema", {"question": "查询销售额", "top_k": 1}
    )
    assert result["is_error"] is False
    assert result["structured_content"]["result"]["database"] == "analytics"
