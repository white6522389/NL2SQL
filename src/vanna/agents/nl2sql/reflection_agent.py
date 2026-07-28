"""Reflection Agent for structured SQL failure diagnosis."""

import json

from vanna.core.llm import LlmMessage, LlmRequest, LlmService
from vanna.core.user import User

from .models import ReflectionResult, SchemaContext


class ReflectionAgent:
    def __init__(self, llm_service: LlmService):
        self.llm_service = llm_service

    async def reflect(
        self, sql: str, error: str, schema: SchemaContext
    ) -> ReflectionResult:
        request = LlmRequest(
            user=User(id="reflection-agent"),
            temperature=0,
            system_prompt=(
                "Analyze the SQL error using only the supplied schema. Return exactly "
                "one JSON object with error_type, error, suggestion, and retryable. "
                "Do not generate replacement SQL."
            ),
            messages=[
                LlmMessage(
                    role="user",
                    content=(
                        f"SQL:\n{sql}\n\nError:\n{error}\n\n"
                        f"Schema:\n{schema.as_prompt()}"
                    ),
                )
            ],
            metadata={"agent": "reflection"},
        )
        response = await self.llm_service.send_request(request)
        text = (response.content or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()[1:]
            if lines and lines[-1].strip() == "```":
                lines.pop()
            text = "\n".join(lines).strip()
        try:
            return ReflectionResult.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("Reflection Agent returned invalid structured output") from exc
