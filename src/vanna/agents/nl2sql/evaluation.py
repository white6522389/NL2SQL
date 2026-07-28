"""Result-oriented evaluation utilities for the NL2SQL workflow."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

from .models import WorkflowResult


class NL2SQLEvalCase(BaseModel):
    id: str
    question: str
    expected_tables: List[str] = Field(default_factory=list)
    expected_filters: Dict[str, str] = Field(default_factory=dict)
    expected_columns: List[str] = Field(default_factory=list)
    expected_rows: List[Dict[str, Any]] = Field(default_factory=list)
    expected_chart_type: Optional[str] = None


class NL2SQLEvalCaseResult(BaseModel):
    case_id: str
    passed: bool
    execution_success: bool
    table_selection_correct: bool
    filter_literals_preserved: bool
    columns_correct: bool
    result_correct: bool
    chart_correct: bool
    elapsed_ms: float
    error: Optional[str] = None


class NL2SQLEvalReport(BaseModel):
    cases: List[NL2SQLEvalCaseResult]

    def metrics(self) -> Dict[str, float]:
        total = len(self.cases)
        if total == 0:
            return {"case_count": 0, "pass_rate": 0.0}

        def rate(field: str) -> float:
            return sum(bool(getattr(case, field)) for case in self.cases) / total

        return {
            "case_count": total,
            "pass_rate": rate("passed"),
            "execution_success_rate": rate("execution_success"),
            "table_selection_accuracy": rate("table_selection_correct"),
            "filter_literal_accuracy": rate("filter_literals_preserved"),
            "column_accuracy": rate("columns_correct"),
            "result_accuracy": rate("result_correct"),
            "chart_accuracy": rate("chart_correct"),
            "average_latency_ms": sum(case.elapsed_ms for case in self.cases) / total,
        }


def load_eval_cases(path: str | Path) -> List[NL2SQLEvalCase]:
    with Path(path).open(encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}
    return [NL2SQLEvalCase.model_validate(item) for item in payload.get("cases", [])]


def evaluate_workflow_result(
    case: NL2SQLEvalCase, result: WorkflowResult, elapsed_ms: float = 0.0
) -> NL2SQLEvalCaseResult:
    sql = result.sql or ""
    actual_tables = {table.name.lower() for table in result.schema_context.tables}
    expected_tables = {table.lower() for table in case.expected_tables}
    table_selection_correct = expected_tables.issubset(actual_tables)

    planned_filters = {str(value) for value in result.plan.filters.values()}
    filter_literals_preserved = all(
        value in sql and value in planned_filters
        for value in case.expected_filters.values()
    )

    execution = result.execution
    actual_columns = set(execution.columns if execution else [])
    columns_correct = set(case.expected_columns).issubset(actual_columns)
    actual_rows = execution.rows if execution else []
    result_correct = all(
        any(all(row.get(key) == value for key, value in expected.items()) for row in actual_rows)
        for expected in case.expected_rows
    )

    actual_chart = result.analysis.chart.type if result.analysis and result.analysis.chart else None
    chart_correct = (
        case.expected_chart_type is None
        or actual_chart == case.expected_chart_type
    )
    execution_success = bool(result.success and execution and execution.success)
    passed = all(
        (
            execution_success,
            table_selection_correct,
            filter_literals_preserved,
            columns_correct,
            result_correct,
            chart_correct,
        )
    )
    return NL2SQLEvalCaseResult(
        case_id=case.id,
        passed=passed,
        execution_success=execution_success,
        table_selection_correct=table_selection_correct,
        filter_literals_preserved=filter_literals_preserved,
        columns_correct=columns_correct,
        result_correct=result_correct,
        chart_correct=chart_correct,
        elapsed_ms=elapsed_ms,
        error=result.error,
    )


async def run_nl2sql_evaluation(
    cases: List[NL2SQLEvalCase],
    workflow_factory: Callable[[], Any],
) -> NL2SQLEvalReport:
    results = []
    for case in cases:
        started = time.perf_counter()
        try:
            workflow_result = await workflow_factory().run(case.question)
            elapsed_ms = (time.perf_counter() - started) * 1000
            results.append(evaluate_workflow_result(case, workflow_result, elapsed_ms))
        except Exception as exc:
            results.append(
                NL2SQLEvalCaseResult(
                    case_id=case.id,
                    passed=False,
                    execution_success=False,
                    table_selection_correct=False,
                    filter_literals_preserved=False,
                    columns_correct=False,
                    result_correct=False,
                    chart_correct=False,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    error=str(exc),
                )
            )
    return NL2SQLEvalReport(cases=results)
