from unittest.mock import AsyncMock

import pytest

from vanna.agents.nl2sql import ReflectionAgent, SchemaColumn, SchemaContext, SchemaTable
from vanna.core.llm import LlmResponse, LlmService


@pytest.mark.asyncio
async def test_explains_unknown_column_with_schema_grounding():
    llm = AsyncMock(spec=LlmService)
    llm.send_request.return_value = LlmResponse(
        content=(
            '{"error_type":"unknown_column","error":"字段不存在",'
            '"suggestion":"orders表中存在amount字段，可用它表达订单金额",'
            '"retryable":true}'
        )
    )
    schema = SchemaContext(
        database="ssss",
        tables=[SchemaTable(name="orders", columns=[
            SchemaColumn(name="amount", data_type="decimal(10,2)", comment="订单金额")
        ])],
    )

    result = await ReflectionAgent(llm).reflect(
        "SELECT sales FROM orders", "Unknown column 'sales'", schema
    )

    assert result.error_type == "unknown_column"
    assert "amount" in result.suggestion
    assert result.retryable is True
    request = llm.send_request.await_args.args[0]
    assert "`amount`" in request.messages[0].content
    assert "Do not generate replacement SQL" in request.system_prompt


@pytest.mark.asyncio
async def test_rejects_invalid_reflection_output():
    llm = AsyncMock(spec=LlmService)
    llm.send_request.return_value = LlmResponse(content="not-json")
    with pytest.raises(ValueError, match="invalid structured output"):
        await ReflectionAgent(llm).reflect(
            "SELECT bad FROM orders", "error", SchemaContext(database="ssss")
        )
