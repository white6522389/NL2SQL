from unittest.mock import AsyncMock, Mock

import pytest

from vanna.agents.nl2sql import (
    AnalysisResult,
    ChartConfig,
    ExecutionResult,
    NL2SQLWorkflow,
    ReflectionResult,
    SQLCandidate,
    SQLValidatorAgent,
    SchemaCatalog,
    SchemaColumn,
    SchemaTable,
    TaskPlan,
)


@pytest.mark.asyncio
async def test_complete_workflow_retries_invalid_sql_then_succeeds():
    plan = TaskPlan(
        task_type="sql_query",
        need_database_query=True,
        need_visualization=True,
        objective="查询华东最高销售商品",
        analysis_type="ranking",
        filters={"region": "华东"},
        execution_steps=["查询", "绘图"],
    )
    catalog = SchemaCatalog(
        database="ssss",
        tables=[
            SchemaTable(
                name="orders",
                columns=[
                    SchemaColumn(name="amount", data_type="decimal"),
                    SchemaColumn(name="region", data_type="varchar"),
                ],
            )
        ],
    )
    planner = Mock()
    planner.plan = AsyncMock(return_value=plan)
    sql_agent = Mock()
    sql_agent.generate = AsyncMock(
        side_effect=[
            SQLCandidate(sql="SELECT o.sales FROM orders o"),
            SQLCandidate(sql="SELECT o.amount FROM orders o WHERE o.region='华东'"),
        ]
    )
    executor = Mock()
    executor.run = AsyncMock(
        return_value=ExecutionResult(
            success=True,
            rows=[{"amount": 100}],
            columns=["amount"],
            row_count=1,
        )
    )
    analyzer = Mock()
    analyzer.analyze = AsyncMock(
        return_value=AnalysisResult(
            summary="最高销售额为100",
            chart=ChartConfig(type="bar", data=[{"amount": 100}]),
        )
    )
    reflection = Mock()
    reflection.reflect = AsyncMock(
        return_value=ReflectionResult(
            error_type="unknown_column",
            error="字段不存在",
            suggestion="使用orders.amount字段",
        )
    )
    repository = Mock()
    repository.load.return_value = catalog
    events = []

    async def collect(event):
        events.append(event)

    workflow = NL2SQLWorkflow(
        planner,
        sql_agent,
        SQLValidatorAgent(),
        executor,
        reflection,
        analyzer,
        repository,
        max_retries=1,
    )

    result = await workflow.run("查询华东销售额最高商品并绘图", collect)

    assert result.success is True
    assert result.sql.startswith("SELECT o.amount")
    assert len(result.reflections) == 1
    assert any(
        event.stage == "validator" and event.status == "failed" for event in events
    )
    assert reflection.reflect.await_count == 1
    assert any(
        event.stage == "reflection" and event.status == "completed"
        for event in events
    )
    assert analyzer.analyze.await_count == 1
