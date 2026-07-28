"""Orchestration for the five-agent NL2SQL workflow."""

from __future__ import annotations

from typing import Awaitable, Callable, Optional

from vanna.services import SchemaRetriever

from .analysis_visualization_agent import AnalysisVisualizationAgent
from .models import ReflectionResult, WorkflowEvent, WorkflowMetrics, WorkflowResult
from .observability import TraceCollector
from .planner_agent import PlannerAgent
from .reflection_agent import ReflectionAgent
from .sql_agent import SQLAgent
from .sql_validator_agent import SQLValidatorAgent

EventHandler = Callable[[WorkflowEvent], Awaitable[None]]


class NL2SQLWorkflow:
    def __init__(self, planner: PlannerAgent, sql_agent: SQLAgent,
        validator: SQLValidatorAgent, executor, reflection: ReflectionAgent,
        analyzer: AnalysisVisualizationAgent, schema_repository, max_retries: int = 2,
        trace: Optional[TraceCollector] = None):
        self.planner = planner
        self.sql_agent = sql_agent
        self.validator = validator
        self.executor = executor
        self.reflection = reflection
        self.analyzer = analyzer
        self.schema_repository = schema_repository
        self.max_retries = max_retries
        self.trace = trace or TraceCollector()

    async def run(
        self,
        query: str,
        on_event: Optional[EventHandler] = None,
        conversation_context: Optional[str] = None,
    ) -> WorkflowResult:
        await self._emit(on_event, "planner", "running", "正在分析任务")
        plan = await self.planner.plan(query, conversation_context=conversation_context)
        await self._emit(on_event, "planner", "completed", "任务规划完成")

        await self._emit(on_event, "schema_rag", "running", "正在检索数据库结构")
        catalog = self.schema_repository.load()
        schema = SchemaRetriever(catalog).retrieve(query)
        await self._emit(on_event, "schema_rag", "completed", "相关数据库结构检索完成")
        reflections = []
        correction = None

        for attempt in range(self.max_retries + 1):
            await self._emit(on_event, "sql_agent", "running", f"正在生成SQL（第{attempt + 1}次）")
            candidate = await self.sql_agent.generate(query, plan, schema,
                correction_context=correction)
            await self._emit(
                on_event,
                "sql_agent",
                "completed",
                f"SQL生成完成（第{attempt + 1}次）",
            )
            await self._emit(on_event, "validator", "running", "正在校验SQL安全与语义")
            validation = self.validator.validate(candidate.sql, catalog)
            if not validation.valid:
                error = validation.reason or "SQL校验失败"
                hint = validation.suggestion or error
                await self._emit(on_event, "validator", "failed", error)
                await self._emit(on_event, "reflection", "running", "正在分析SQL校验错误")
                try:
                    reflected = await self.reflection.reflect(
                        candidate.sql,
                        f"{error}\nValidator suggestion: {hint}",
                        schema,
                    )
                except ValueError:
                    reflected = ReflectionResult(
                        error_type=validation.error_type or "validation_error",
                        error=error,
                        suggestion=hint,
                    )
                reflections.append(reflected)
                await self._emit(
                    on_event, "reflection", "completed", reflected.suggestion
                )
                if not reflected.retryable:
                    break
                correction = reflected.suggestion
                continue

            await self._emit(on_event, "validator", "completed", "SQL安全校验通过")
            await self._emit(on_event, "executor", "running", "正在执行只读查询")
            execution = await self.executor.run(candidate.sql)
            if execution.success:
                await self._emit(on_event, "executor", "completed", f"查询返回{execution.row_count}行")
                await self._emit(on_event, "analysis", "running", "正在分析结果并生成图表")
                analysis = await self.analyzer.analyze(plan, execution)
                await self._emit(on_event, "analysis", "completed", "分析与图表生成完成")
                return WorkflowResult(success=True, plan=plan, schema_context=schema,
                    sql=candidate.sql, validation=validation, execution=execution,
                    reflections=reflections, analysis=analysis,
                    metrics=self._metrics(len(reflections)))

            await self._emit(on_event, "executor", "failed", execution.error or "执行失败")
            await self._emit(on_event, "reflection", "running", "正在分析SQL执行错误")
            reflected = await self.reflection.reflect(candidate.sql,
                execution.error or "unknown execution error", schema)
            reflections.append(reflected)
            await self._emit(on_event, "reflection", "completed", reflected.suggestion)
            if not reflected.retryable:
                break
            correction = reflected.suggestion

        return WorkflowResult(success=False, plan=plan, schema_context=schema,
            reflections=reflections, metrics=self._metrics(len(reflections)),
            error="SQL在最大重试次数内未能成功执行")

    async def _emit(self, handler: Optional[EventHandler], stage: str, status: str, message: str):
        elapsed_ms = self.trace.stage_event(stage, status)
        if handler:
            await handler(WorkflowEvent(
                stage=stage,
                status=status,
                message=message,
                trace_id=self.trace.trace_id,
                elapsed_ms=elapsed_ms,
            ))

    def _metrics(self, retry_count: int) -> WorkflowMetrics:
        return WorkflowMetrics(
            trace_id=self.trace.trace_id,
            total_elapsed_ms=self.trace.total_elapsed_ms(),
            stage_timings_ms=self.trace.stage_timings_ms,
            llm_call_count=self.trace.llm_call_count,
            prompt_tokens=self.trace.prompt_tokens,
            completion_tokens=self.trace.completion_tokens,
            total_tokens=self.trace.total_tokens,
            retry_count=retry_count,
        )
