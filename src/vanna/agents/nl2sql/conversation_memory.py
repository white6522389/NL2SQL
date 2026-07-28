"""Bounded in-memory structured conversation state for follow-up questions."""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from typing import Dict, Optional

from pydantic import BaseModel, Field

from .models import TaskPlan, WorkflowResult


class ConversationState(BaseModel):
    conversation_id: str
    last_question: str
    last_plan: TaskPlan
    last_sql: Optional[str] = None
    result_columns: list[str] = Field(default_factory=list)
    result_rows: list[Dict] = Field(default_factory=list)
    updated_at: float = Field(default_factory=time.time)

    def as_planner_context(self) -> str:
        return json.dumps(
            {
                "previous_question": self.last_question,
                "previous_plan": self.last_plan.model_dump(mode="json"),
                "previous_sql": self.last_sql,
                "previous_result_columns": self.result_columns,
                "previous_result_preview": self.result_rows[:5],
            },
            ensure_ascii=False,
        )


class ConversationMemoryStore:
    def __init__(self, max_conversations: int = 500, ttl_seconds: int = 3600):
        self.max_conversations = max_conversations
        self.ttl_seconds = ttl_seconds
        self._states: OrderedDict[str, ConversationState] = OrderedDict()

    def get(self, conversation_id: str) -> Optional[ConversationState]:
        state = self._states.get(conversation_id)
        if state is None:
            return None
        if time.time() - state.updated_at > self.ttl_seconds:
            del self._states[conversation_id]
            return None
        self._states.move_to_end(conversation_id)
        return state

    def save(
        self, conversation_id: str, question: str, result: WorkflowResult
    ) -> ConversationState:
        execution = result.execution
        state = ConversationState(
            conversation_id=conversation_id,
            last_question=question,
            last_plan=result.plan,
            last_sql=result.sql,
            result_columns=execution.columns if execution else [],
            result_rows=execution.rows[:20] if execution else [],
        )
        self._states[conversation_id] = state
        self._states.move_to_end(conversation_id)
        while len(self._states) > self.max_conversations:
            self._states.popitem(last=False)
        return state

    def clear(self, conversation_id: str) -> None:
        self._states.pop(conversation_id, None)
