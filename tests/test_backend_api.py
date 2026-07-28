import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from backend.app import app
from vanna.agents.nl2sql import (
    AnalysisResult,
    ExecutionResult,
    SchemaContext,
    TaskPlan,
    WorkflowEvent,
    WorkflowResult,
)


@pytest.mark.asyncio
async def test_analyze_endpoint_streams_stage_and_result(monkeypatch):
    workflow = Mock()
    plan = TaskPlan(
        task_type="sql_query",
        need_database_query=True,
        need_visualization=False,
        objective="查询销售额",
        execution_steps=["查询"],
    )

    async def run(query, on_event, conversation_context=None):
        assert query == "查询销售额"
        await on_event(WorkflowEvent(stage="planner", status="completed", message="完成"))
        return WorkflowResult(
            success=True,
            plan=plan,
            schema_context=SchemaContext(database="ssss"),
            sql="SELECT amount FROM orders",
            execution=ExecutionResult(
                success=True, rows=[{"amount": 100}], columns=["amount"], row_count=1
            ),
            analysis=AnalysisResult(summary="销售额为100"),
        )

    workflow.run = AsyncMock(side_effect=run)
    monkeypatch.setattr("backend.app.create_workflow", lambda: workflow)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/analyze", json={"question": "查询销售额"})

    assert response.status_code == 200
    events = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: {")
    ]
    assert events[0]["type"] == "stage"
    assert events[1]["type"] == "result"
    assert events[1]["data"]["sql"] == "SELECT amount FROM orders"
