from unittest.mock import AsyncMock

import pytest

from vanna.agents.nl2sql import (
    SQLAgent,
    SchemaColumn,
    SchemaContext,
    SchemaTable,
    TaskPlan,
)
from vanna.core.llm import LlmResponse, LlmService


@pytest.mark.asyncio
async def test_generates_sql_from_retrieved_schema():
    llm = AsyncMock(spec=LlmService)
    llm.send_request.return_value = LlmResponse(
        content="""```sql
SELECT p.name, SUM(o.amount) AS total_sales
FROM orders o JOIN products p ON p.id = o.product_id
WHERE o.region = '华东'
GROUP BY p.id, p.name
ORDER BY total_sales DESC
LIMIT 1;
```"""
    )
    agent = SQLAgent(llm)
    plan = TaskPlan(
        task_type="sql_query",
        need_database_query=True,
        need_visualization=False,
        objective="查询华东销售额最高商品",
        analysis_type="ranking",
        filters={"region": "华东"},
        execution_steps=["查询并排名"],
    )
    schema = SchemaContext(
        database="ssss",
        tables=[
            SchemaTable(
                name="orders",
                columns=[
                    SchemaColumn(name="amount", data_type="decimal(10,2)"),
                    SchemaColumn(
                        name="region",
                        data_type="varchar(50)",
                        sample_values=["华东", "华南", "华北", "华中"],
                    ),
                    SchemaColumn(name="product_id", data_type="bigint"),
                ],
            ),
            SchemaTable(
                name="products",
                columns=[
                    SchemaColumn(name="id", data_type="bigint"),
                    SchemaColumn(name="name", data_type="varchar(100)"),
                ],
            ),
        ],
    )

    candidate = await agent.generate("查询华东销售额最高商品", plan, schema)

    assert candidate.sql.startswith("SELECT p.name")
    assert "WHERE o.region = '华东'" in candidate.sql
    assert candidate.referenced_tables == ["orders", "products"]
    request = llm.send_request.await_args.args[0]
    assert "Table `orders`" in request.messages[0].content
    assert "actual values: '华东', '华南', '华北', '华中'" in request.messages[0].content
    assert "Never invent a table or column" in request.system_prompt
    assert "Preserve business filter literals" in request.system_prompt
    assert "human-readable name column" in request.system_prompt


@pytest.mark.asyncio
async def test_requires_retrieved_schema():
    agent = SQLAgent(AsyncMock(spec=LlmService))
    plan = TaskPlan(
        task_type="sql_query",
        need_database_query=True,
        need_visualization=False,
        objective="查询销售额",
        execution_steps=["查询"],
    )

    with pytest.raises(ValueError, match="at least one relevant table"):
        await agent.generate("查询销售额", plan, SchemaContext(database="ssss"))
