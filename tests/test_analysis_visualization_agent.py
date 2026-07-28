from unittest.mock import AsyncMock

import pytest

from vanna.agents.nl2sql import AnalysisVisualizationAgent, ExecutionResult, TaskPlan
from vanna.core.llm import LlmResponse, LlmService


def plan(need_visualization=True, analysis_type="trend"):
    return TaskPlan(task_type="sql_query", need_database_query=True,
        need_visualization=need_visualization, objective="分析销售额",
        analysis_type=analysis_type, execution_steps=["分析结果"])


@pytest.mark.asyncio
async def test_generates_line_chart_for_time_series():
    llm = AsyncMock(spec=LlmService)
    llm.send_request.return_value = LlmResponse(content='''{
      "summary":"销售额呈增长趋势",
      "insights":["2月高于1月"],
      "chart":{"type":"line","title":"月度销售额","x_field":"month",
      "y_field":"sales","data":[{"month":"1月","sales":10000},{"month":"2月","sales":12000}]}
    }''')
    execution = ExecutionResult(success=True, columns=["month", "sales"],
        rows=[{"month":"1月","sales":10000},{"month":"2月","sales":12000}], row_count=2)

    result = await AnalysisVisualizationAgent(llm).analyze(plan(), execution)
    assert result.summary == "销售额呈增长趋势"
    assert result.chart.type == "line"
    assert result.chart.x_field == "month"


@pytest.mark.asyncio
async def test_suppresses_chart_when_plan_does_not_request_it():
    llm = AsyncMock(spec=LlmService)
    llm.send_request.return_value = LlmResponse(content='''{
      "summary":"销售额为10000","insights":[],
      "chart":{"type":"bar","data":[{"sales":10000}]}
    }''')
    result = await AnalysisVisualizationAgent(llm).analyze(
        plan(False), ExecutionResult(success=True, rows=[{"sales":10000}], columns=["sales"], row_count=1))
    assert result.chart is None


@pytest.mark.asyncio
async def test_handles_empty_result_without_llm_call():
    llm = AsyncMock(spec=LlmService)
    result = await AnalysisVisualizationAgent(llm).analyze(
        plan(), ExecutionResult(success=True))
    assert "没有" in result.summary
    llm.send_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_normalizes_single_insight_string_from_llm():
    llm = AsyncMock(spec=LlmService)
    llm.send_request.return_value = LlmResponse(
        content='{"summary":"销售额为59690",'
        '"insights":"当前最高销售额为59690", "chart":null}'
    )
    execution = ExecutionResult(
        success=True,
        columns=["sales"],
        rows=[{"sales": 59690}],
        row_count=1,
    )

    result = await AnalysisVisualizationAgent(llm).analyze(plan(False), execution)

    assert result.insights == ["当前最高销售额为59690"]


@pytest.mark.asyncio
async def test_builds_bar_chart_when_llm_omits_requested_chart():
    llm = AsyncMock(spec=LlmService)
    llm.send_request.return_value = LlmResponse(
        content='{"summary":"MacBook销售额最高","insights":[],"chart":null}'
    )
    execution = ExecutionResult(
        success=True,
        columns=["product_name", "total_sales"],
        rows=[{"product_name": "MacBook", "total_sales": 12999}],
        row_count=1,
    )

    result = await AnalysisVisualizationAgent(llm).analyze(
        plan(True, "ranking"), execution
    )

    assert result.chart is not None
    assert result.chart.type == "bar"
    assert result.chart.x_field == "product_name"
    assert result.chart.y_field == "total_sales"
    assert result.chart.data == execution.rows
