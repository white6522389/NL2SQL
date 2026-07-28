from unittest.mock import AsyncMock

import pytest

from vanna.agents.nl2sql.observability import ObservedLlmService, TraceCollector
from vanna.core.llm import LlmRequest, LlmResponse, LlmService
from vanna.core.user import User


@pytest.mark.asyncio
async def test_observed_llm_collects_call_and_token_usage():
    delegate = AsyncMock(spec=LlmService)
    delegate.send_request.return_value = LlmResponse(
        content="ok",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )
    trace = TraceCollector()
    observed = ObservedLlmService(delegate, trace)

    await observed.send_request(
        LlmRequest(user=User(id="test"), messages=[], temperature=0)
    )

    assert trace.llm_call_count == 1
    assert trace.prompt_tokens == 10
    assert trace.completion_tokens == 5
    assert trace.total_tokens == 15


def test_trace_collects_stage_duration():
    trace = TraceCollector()

    assert trace.stage_event("planner", "running") is None
    elapsed = trace.stage_event("planner", "completed")

    assert elapsed is not None
    assert "planner" in trace.stage_timings_ms
