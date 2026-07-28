import json
from unittest.mock import AsyncMock

import pytest

from vanna.agents.nl2sql import PlannerAgent, PlannerOutputError, TaskType
from vanna.core.llm import LlmResponse, LlmService


def make_planner(payload):
    llm = AsyncMock(spec=LlmService)
    llm.send_request.return_value = LlmResponse(content=json.dumps(payload))
    return PlannerAgent(llm), llm


@pytest.mark.asyncio
async def test_plans_sales_query():
    planner, llm = make_planner(
        {
            "task_type": "sql_query",
            "need_database_query": True,
            "need_visualization": False,
            "objective": "统计销售额",
            "analysis_type": "aggregation",
            "time_range": None,
            "filters": {},
            "execution_steps": ["获取销售数据", "汇总销售额"],
        }
    )

    plan = await planner.plan("查询销售额")

    assert plan.task_type is TaskType.SQL_QUERY
    assert plan.need_database_query is True
    assert plan.need_visualization is False
    assert plan.analysis_type == "aggregation"
    request = llm.send_request.await_args.args[0]
    assert request.messages[0].content == "查询销售额"
    assert "Do not generate SQL" in request.system_prompt


@pytest.mark.asyncio
async def test_extracts_filters_and_visualization_request():
    planner, _ = make_planner(
        {
            "task_type": "sql_query",
            "need_database_query": True,
            "need_visualization": True,
            "objective": "找出2025年华东地区销售额最高的商品并绘制柱状图",
            "analysis_type": "ranking",
            "time_range": "2025",
            "filters": {"region": "华东"},
            "execution_steps": ["查询销售数据", "按商品排名", "生成柱状图"],
        }
    )

    plan = await planner.plan("查询2025年华东地区销售额最高的商品，并生成柱状图")

    assert plan.need_visualization is True
    assert plan.analysis_type == "ranking"
    assert plan.time_range == "2025"
    assert plan.filters == {"region": "华东"}


@pytest.mark.asyncio
async def test_rejects_invalid_planner_output():
    llm = AsyncMock(spec=LlmService)
    llm.send_request.return_value = LlmResponse(content="not json")
    planner = PlannerAgent(llm)

    with pytest.raises(PlannerOutputError, match="JSON object"):
        await planner.plan("查询销售额")


@pytest.mark.asyncio
async def test_rejects_empty_user_query_without_calling_llm():
    planner, llm = make_planner({})

    with pytest.raises(ValueError, match="must not be empty"):
        await planner.plan("   ")

    llm.send_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_passes_structured_context_for_follow_up():
    planner, llm = make_planner(
        {
            "task_type": "sql_query",
            "need_database_query": True,
            "need_visualization": True,
            "objective": "查询2025年华南最高销售商品",
            "analysis_type": "ranking",
            "time_range": "2025",
            "filters": {"region": "华南"},
            "execution_steps": ["查询", "绘图"],
        }
    )

    plan = await planner.plan(
        "那华南呢？",
        conversation_context=(
            '{"previous_plan":{"time_range":"2025",'
            '"filters":{"region":"华东"}}}'
        ),
    )

    request = llm.send_request.await_args.args[0]
    assert "Previous structured conversation context" in request.messages[0].content
    assert "Current user message:\n那华南呢？" in request.messages[0].content
    assert plan.time_range == "2025"
    assert plan.filters == {"region": "华南"}
