"""Planner Agent for converting a user question into a structured task plan."""

from __future__ import annotations

import json
from typing import Optional

from pydantic import ValidationError

from vanna.core.llm import LlmMessage, LlmRequest, LlmService
from vanna.core.user import User

from .models import TaskPlan


PLANNER_SYSTEM_PROMPT = """You are the Planner Agent in an NL2SQL data analysis system.
Your only responsibility is to convert the user's request into an execution plan.
Do not generate SQL and do not answer the data question.

Decide whether a database query is required, whether a chart is requested or useful,
the analysis type, time range, filters, objective, and execution steps.
Preserve every business filter value exactly as written by the user. Never translate,
romanize, normalize, or paraphrase regions, cities, categories, product names, or
customer names. For example, the filter value 华东 must remain 华东, not East China.

Return exactly one JSON object matching this schema:
{
  "task_type": "sql_query | general_question | clarification",
  "need_database_query": true,
  "need_visualization": false,
  "objective": "concise task objective",
  "analysis_type": "aggregation | ranking | trend | comparison | proportion | null",
  "time_range": "explicit time range or null",
  "filters": {"filter name": "filter value"},
  "execution_steps": ["step 1", "step 2"]
}

Use sql_query for questions that require database facts. Use clarification only when
essential information is missing and no safe execution plan can be produced.
When previous structured conversation context is supplied, inherit constraints and
the analysis objective that the current follow-up does not replace. The current user
message always has priority. A phrase such as “那华南呢” should keep the previous
year and metric while replacing region with 华南.
Output JSON only, without Markdown fences or commentary."""


class PlannerOutputError(ValueError):
    """Raised when the LLM does not return a valid TaskPlan."""


class PlannerAgent:
    """Generate validated, structured plans without executing any task."""

    def __init__(self, llm_service: LlmService, model_temperature: float = 0.0):
        self.llm_service = llm_service
        self.model_temperature = model_temperature

    async def plan(
        self,
        user_query: str,
        user: Optional[User] = None,
        conversation_context: Optional[str] = None,
    ) -> TaskPlan:
        """Plan a user request and return a validated TaskPlan."""
        query = user_query.strip()
        if not query:
            raise ValueError("user_query must not be empty")

        planner_user = user or User(id="planner-agent")
        content = query
        if conversation_context:
            content = (
                f"Previous structured conversation context:\n{conversation_context}\n\n"
                f"Current user message:\n{query}"
            )
        request = LlmRequest(
            user=planner_user,
            system_prompt=PLANNER_SYSTEM_PROMPT,
            messages=[LlmMessage(role="user", content=content)],
            temperature=self.model_temperature,
            stream=False,
            max_tokens=600,
            metadata={"agent": "planner"},
        )
        response = await self.llm_service.send_request(request)
        if not response.content:
            raise PlannerOutputError("Planner LLM returned an empty response")

        payload = self._extract_json_object(response.content)
        try:
            return TaskPlan.model_validate(payload)
        except ValidationError as exc:
            raise PlannerOutputError(
                f"Planner response does not match TaskPlan: {exc}"
            ) from exc

    @staticmethod
    def _extract_json_object(content: str) -> object:
        """Extract one JSON object, tolerating accidental Markdown fences."""
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise PlannerOutputError("Planner response does not contain a JSON object")

        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise PlannerOutputError(
                f"Planner response contains invalid JSON: {exc.msg}"
            ) from exc
