"""Lightweight request-scoped observability for the NL2SQL workflow."""

from __future__ import annotations

import time
import uuid
from typing import Any, AsyncGenerator, Dict, List

from vanna.core.llm import LlmRequest, LlmResponse, LlmService, LlmStreamChunk


class TraceCollector:
    def __init__(self) -> None:
        self.trace_id = uuid.uuid4().hex
        self.started_at = time.perf_counter()
        self.llm_call_count = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.stage_timings_ms: Dict[str, float] = {}
        self._stage_started: Dict[str, float] = {}

    def stage_event(self, stage: str, status: str) -> float | None:
        now = time.perf_counter()
        if status == "running":
            self._stage_started[stage] = now
            return None
        started = self._stage_started.pop(stage, None)
        if started is None:
            return None
        elapsed = (now - started) * 1000
        self.stage_timings_ms[stage] = self.stage_timings_ms.get(stage, 0) + elapsed
        return elapsed

    def record_llm(self, response: LlmResponse) -> None:
        self.llm_call_count += 1
        usage = response.usage or {}
        self.prompt_tokens += usage.get("prompt_tokens", usage.get("input_tokens", 0))
        self.completion_tokens += usage.get(
            "completion_tokens", usage.get("output_tokens", 0)
        )
        self.total_tokens += usage.get("total_tokens", 0)

    def total_elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started_at) * 1000


class ObservedLlmService(LlmService):
    """Transparent LLM wrapper that records calls, latency, and token usage."""

    def __init__(self, delegate: LlmService, trace: TraceCollector):
        self.delegate = delegate
        self.trace = trace

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        response = await self.delegate.send_request(request)
        self.trace.record_llm(response)
        return response

    async def stream_request(
        self, request: LlmRequest
    ) -> AsyncGenerator[LlmStreamChunk, None]:
        async for chunk in self.delegate.stream_request(request):
            yield chunk

    async def validate_tools(self, tools: List[Any]) -> List[str]:
        return await self.delegate.validate_tools(tools)
