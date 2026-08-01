"""stdio MCP server used by the integration test."""

from types import SimpleNamespace

from vanna.agents.nl2sql import (
    ExecutionResult,
    SchemaCatalog,
    SchemaColumn,
    SchemaTable,
)
from vanna.integrations.mcp import create_nl2sql_mcp_server


class Repository:
    def load(self):
        return SchemaCatalog(
            database="analytics",
            tables=[SchemaTable(
                name="orders",
                comment="销售订单",
                columns=[SchemaColumn(name="amount", data_type="decimal")],
            )],
        )


class Executor:
    async def run(self, sql):
        return ExecutionResult(
            success=True,
            rows=[{"amount": 10}],
            columns=["amount"],
            row_count=1,
        )


class Workflow:
    async def run(self, question, conversation_context=None):
        return SimpleNamespace(model_dump=lambda mode: {
            "success": True,
            "question": question,
            "conversation_context": conversation_context,
        })


if __name__ == "__main__":
    create_nl2sql_mcp_server(Workflow, Repository(), Executor()).run()
