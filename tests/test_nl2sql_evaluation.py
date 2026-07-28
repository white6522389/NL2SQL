from vanna.agents.nl2sql import (
    AnalysisResult,
    ChartConfig,
    ExecutionResult,
    SchemaContext,
    SchemaTable,
    TaskPlan,
    WorkflowResult,
)
from vanna.agents.nl2sql.evaluation import (
    NL2SQLEvalCase,
    NL2SQLEvalReport,
    evaluate_workflow_result,
    load_eval_cases,
)


def successful_result():
    return WorkflowResult(
        success=True,
        plan=TaskPlan(
            task_type="sql_query",
            need_database_query=True,
            need_visualization=True,
            objective="查询华东最高销售商品",
            analysis_type="ranking",
            filters={"region": "华东"},
            execution_steps=["查询"],
        ),
        schema_context=SchemaContext(
            database="ssss",
            tables=[SchemaTable(name="orders"), SchemaTable(name="products")],
        ),
        sql="SELECT product_name, SUM(amount) total_sales FROM orders JOIN products ON 1=1 WHERE region='华东'",
        execution=ExecutionResult(
            success=True,
            columns=["product_name", "total_sales"],
            rows=[{"product_name": "MacBook", "total_sales": 12999}],
            row_count=1,
        ),
        analysis=AnalysisResult(
            summary="MacBook最高",
            chart=ChartConfig(type="bar", data=[{"product_name": "MacBook", "total_sales": 12999}]),
        ),
    )


def test_evaluates_business_result_instead_of_sql_text_only():
    case = NL2SQLEvalCase(
        id="east",
        question="查询华东最高销售商品",
        expected_tables=["orders", "products"],
        expected_filters={"region": "华东"},
        expected_columns=["product_name", "total_sales"],
        expected_rows=[{"product_name": "MacBook", "total_sales": 12999}],
        expected_chart_type="bar",
    )

    result = evaluate_workflow_result(case, successful_result(), elapsed_ms=25)

    assert result.passed is True
    assert result.result_correct is True
    assert result.filter_literals_preserved is True


def test_report_calculates_rates():
    case = NL2SQLEvalCase(id="east", question="q")
    first = evaluate_workflow_result(case, successful_result())
    failed = first.model_copy(update={"passed": False, "execution_success": False})

    metrics = NL2SQLEvalReport(cases=[first, failed]).metrics()

    assert metrics["case_count"] == 2
    assert metrics["pass_rate"] == 0.5
    assert metrics["execution_success_rate"] == 0.5


def test_loads_project_benchmark():
    cases = load_eval_cases("evals/nl2sql_cases.yaml")

    assert len(cases) >= 8
    assert cases[0].expected_filters == {"region": "华东"}
