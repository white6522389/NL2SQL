"""Schema-grounded SQL generation agent."""

from __future__ import annotations

from typing import Optional

from vanna.core.llm import LlmMessage, LlmRequest, LlmService
from vanna.core.user import User

from .models import SQLCandidate, SchemaContext, TaskPlan


SQL_SYSTEM_PROMPT = """You are the SQL Agent in an NL2SQL system targeting MySQL 5.7.
Generate one SQL query that fulfills the task plan using only the supplied schema.
Never invent a table or column. Do not query information_schema.
Preserve business filter literals from the user's request exactly as written. Never
translate, romanize, normalize, or paraphrase values such as regions, cities,
categories, product names, or customer names. Prefer an exact value listed in the
schema's `actual values` metadata when it matches the user's wording.
When the user asks about a business entity such as a product or customer, join the
related table when possible and return a human-readable name column rather than only
a numeric ID. For charts, prefer readable labels such as product_name over product_id.
Return SQL only, without explanations or Markdown. A separate Validator Agent will
perform syntax and safety checks later."""


class SQLAgentOutputError(ValueError):
    """Raised when SQL Agent returns no usable SQL statement."""


class SQLAgent:
    """Generate SQL from a plan augmented with retrieved schema knowledge."""

    def __init__(self, llm_service: LlmService, model_temperature: float = 0.0):
        self.llm_service = llm_service
        self.model_temperature = model_temperature

    async def generate(
        self,
        user_query: str,
        task_plan: TaskPlan,
        schema: SchemaContext,
        user: Optional[User] = None,
        correction_context: Optional[str] = None,
    ) -> SQLCandidate:
        if not schema.tables:
            raise ValueError("schema must contain at least one relevant table")

        prompt = (
            f"User request:\n{user_query.strip()}\n\n"
            f"Task plan:\n{task_plan.model_dump_json()}\n\n"
            f"Retrieved schema:\n{schema.as_prompt()}"
        )
        if correction_context:
            prompt += f"\n\nCorrection required after the previous attempt:\n{correction_context}"
        request = LlmRequest(
            user=user or User(id="sql-agent"),
            system_prompt=SQL_SYSTEM_PROMPT,
            messages=[LlmMessage(role="user", content=prompt)],
            temperature=self.model_temperature,
            stream=False,
            max_tokens=1000,
            metadata={"agent": "sql", "database": schema.database},
        )
        response = await self.llm_service.send_request(request)
        sql = self._extract_sql(response.content or "")
        return SQLCandidate(
            sql=sql,
            referenced_tables=[table.name for table in schema.tables],
        )

    @staticmethod
    def _extract_sql(content: str) -> str:
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            lines = lines[1:] if lines else lines
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        if not text:
            raise SQLAgentOutputError("SQL Agent returned an empty response")
        return text
