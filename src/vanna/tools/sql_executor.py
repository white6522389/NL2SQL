"""Bounded, read-only SQL execution tool for the NL2SQL workflow."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, Type

from pydantic import BaseModel, Field

from vanna.agents.nl2sql.models import ExecutionResult
from vanna.core.tool import Tool, ToolContext, ToolResult


class SQLExecutorArgs(BaseModel):
    sql: str = Field(min_length=1)


class SQLExecutorTool(Tool[SQLExecutorArgs]):
    """Execute validated SQL with timeout and result-size boundaries."""

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        timeout_seconds: float = 15.0,
        max_rows: int = 500,
    ):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_rows < 1:
            raise ValueError("max_rows must be at least 1")
        self.connection_factory = connection_factory
        self.timeout_seconds = timeout_seconds
        self.max_rows = max_rows

    @property
    def name(self) -> str:
        return "execute_sql"

    @property
    def description(self) -> str:
        return "Execute one SQL query that has already passed SQL Validator Agent"

    def get_args_schema(self) -> Type[SQLExecutorArgs]:
        return SQLExecutorArgs

    async def run(self, sql: str) -> ExecutionResult:
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._execute_sync, sql),
                timeout=self.timeout_seconds,
            )
            result.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            return result
        except asyncio.TimeoutError:
            return ExecutionResult(
                success=False,
                error=f"查询超过{self.timeout_seconds:g}秒，已终止等待",
                elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        except Exception as exc:
            return ExecutionResult(
                success=False,
                error=str(exc),
                elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
            )

    def _execute_sync(self, sql: str) -> ExecutionResult:
        connection = self.connection_factory()
        try:
            cursor = connection.cursor()
            cursor.execute(sql)
            rows = list(cursor.fetchmany(self.max_rows + 1))
            columns = [item[0] for item in (cursor.description or [])]
            cursor.close()
            truncated = len(rows) > self.max_rows
            rows = rows[: self.max_rows]
            normalized = [
                dict(row) if isinstance(row, dict) else dict(zip(columns, row))
                for row in rows
            ]
            return ExecutionResult(
                success=True,
                rows=normalized,
                columns=columns,
                row_count=len(normalized),
                truncated=truncated,
            )
        finally:
            connection.close()

    async def execute(
        self, context: ToolContext, args: SQLExecutorArgs
    ) -> ToolResult:
        result = await self.run(args.sql)
        data: Dict[str, Any] = result.model_dump(mode="json")
        return ToolResult(
            success=result.success,
            result_for_llm=str(data),
            error=result.error,
            metadata=data,
        )
