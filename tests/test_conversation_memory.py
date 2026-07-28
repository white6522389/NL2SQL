from vanna.agents.nl2sql import ExecutionResult, SchemaContext, TaskPlan, WorkflowResult
from vanna.agents.nl2sql.conversation_memory import ConversationMemoryStore


def result(region="华东"):
    return WorkflowResult(
        success=True,
        plan=TaskPlan(
            task_type="sql_query",
            need_database_query=True,
            need_visualization=True,
            objective=f"查询{region}最高销售商品",
            analysis_type="ranking",
            time_range="2025",
            filters={"region": region},
            execution_steps=["查询", "绘图"],
        ),
        schema_context=SchemaContext(database="ssss"),
        sql=f"SELECT product_name FROM orders WHERE region='{region}'",
        execution=ExecutionResult(
            success=True,
            columns=["product_name", "total_sales"],
            rows=[{"product_name": "MacBook", "total_sales": 12999}],
            row_count=1,
        ),
    )


def test_stores_structured_context_for_follow_up():
    store = ConversationMemoryStore()
    store.save("conversation-1", "查询2025年华东最高销售商品", result())

    state = store.get("conversation-1")
    context = state.as_planner_context()

    assert '"time_range": "2025"' in context
    assert '"region": "华东"' in context
    assert "MacBook" in context


def test_evicts_oldest_conversation_when_bounded():
    store = ConversationMemoryStore(max_conversations=1)
    store.save("first", "q1", result())
    store.save("second", "q2", result("华南"))

    assert store.get("first") is None
    assert store.get("second") is not None
