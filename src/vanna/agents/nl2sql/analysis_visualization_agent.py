"""Agent for grounded result analysis and chart selection."""

import json
from numbers import Number

from vanna.core.llm import LlmMessage, LlmRequest, LlmService
from vanna.core.user import User

from .models import AnalysisResult, ChartConfig, ExecutionResult, TaskPlan


class AnalysisVisualizationAgent:
    """Summarize query rows and optionally produce a chart description."""

    def __init__(self, llm_service: LlmService):
        self.llm_service = llm_service

    async def analyze(
        self, plan: TaskPlan, execution: ExecutionResult
    ) -> AnalysisResult:
        if not execution.success:
            raise ValueError("cannot analyze a failed execution result")
        if not execution.rows:
            return AnalysisResult(summary="查询成功，但没有符合条件的数据。")

        payload = {
            "plan": plan.model_dump(mode="json"),
            "columns": execution.columns,
            "rows": execution.rows[:100],
            "truncated": execution.truncated,
        }
        request = LlmRequest(
            user=User(id="analysis-visualization-agent"),
            temperature=0,
            max_tokens=1200,
            system_prompt=(
                "Analyze only the supplied query result; never invent values. Respond in "
                "Chinese as JSON with summary, insights, and chart. chart must be null when "
                "visualization is not needed. When plan.need_visualization is true, chart must "
                "not be null. Otherwise chart supports: line for time trends, "
                "bar for category comparisons/rankings, pie for proportions. Chart fields are "
                "type,title,x_field,y_field,name_field,value_field,data. Copy chart data from "
                "the supplied rows. Return JSON only."
            ),
            messages=[LlmMessage(role="user", content=json.dumps(payload, ensure_ascii=False))],
            metadata={"agent": "analysis_visualization"},
        )
        response = await self.llm_service.send_request(request)
        text = (response.content or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()[1:]
            if lines and lines[-1].strip() == "```":
                lines.pop()
            text = "\n".join(lines).strip()
        result = AnalysisResult.model_validate(json.loads(text))
        if result.chart and result.chart.type not in {"line", "bar", "pie"}:
            raise ValueError(f"unsupported chart type: {result.chart.type}")
        if not plan.need_visualization:
            result.chart = None
        elif not self._is_usable_chart(result.chart):
            result.chart = self._build_fallback_chart(plan, execution)
        return result

    @staticmethod
    def _is_usable_chart(chart: ChartConfig | None) -> bool:
        if chart is None or not chart.data:
            return False
        if chart.type == "pie":
            return bool(chart.name_field and chart.value_field)
        return bool(chart.x_field and chart.y_field)

    @staticmethod
    def _build_fallback_chart(
        plan: TaskPlan, execution: ExecutionResult
    ) -> ChartConfig | None:
        """Create a deterministic chart when the LLM omits unusable chart JSON."""
        if not execution.rows or not execution.columns:
            return None

        first_row = execution.rows[0]
        numeric_columns = [
            column
            for column in execution.columns
            if isinstance(first_row.get(column), Number)
            and not isinstance(first_row.get(column), bool)
        ]
        label_columns = [
            column for column in execution.columns if column not in numeric_columns
        ]
        if not numeric_columns:
            return None

        value_field = numeric_columns[-1]
        label_field = label_columns[0] if label_columns else execution.columns[0]
        chart_type = {
            "trend": "line",
            "proportion": "pie",
        }.get(plan.analysis_type or "", "bar")
        data = execution.rows[:100]

        if chart_type == "pie":
            return ChartConfig(
                type="pie",
                title=plan.objective,
                name_field=label_field,
                value_field=value_field,
                data=data,
            )
        return ChartConfig(
            type=chart_type,
            title=plan.objective,
            x_field=label_field,
            y_field=value_field,
            data=data,
        )
