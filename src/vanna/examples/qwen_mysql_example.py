"""Qwen (DashScope OpenAI-compatible API) + MySQL server example."""

from __future__ import annotations

import importlib.util
import os

import httpx

from vanna import Agent, AgentConfig, User
from vanna.capabilities.sql_runner import RunSqlToolArgs
from vanna.core.registry import ToolRegistry
from vanna.core.system_prompt import DefaultSystemPromptBuilder
from vanna.core.tool import ToolContext
from vanna.core.user import RequestContext, UserResolver
from vanna.integrations.local import LocalFileSystem
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.mysql import MySQLRunner
from vanna.integrations.openai import OpenAILlmService
from vanna.tools import RunSqlTool


def _load_and_validate_env() -> None:
    if importlib.util.find_spec("dotenv") is None:
        raise RuntimeError(
            "python-dotenv is required; install it with: pip install python-dotenv"
        )

    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.getcwd(), ".env"), override=False)
    required = [
        "DASHSCOPE_API_KEY",
        "MYSQL_HOST",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "MYSQL_DATABASE",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing required .env variables: {', '.join(missing)}")


class DemoUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        return User(
            id="qwen-mysql-demo",
            username="demo",
            group_memberships=["data_reader"],
        )


class ReadOnlyMySQLRunner(MySQLRunner):
    """Allow only a single SELECT statement from the demo agent."""

    async def run_sql(
        self, args: RunSqlToolArgs, context: ToolContext
    ):
        sql = args.sql.strip()
        normalized = sql.rstrip(";").strip()
        if not normalized.upper().startswith("SELECT") or ";" in normalized:
            raise PermissionError("This demo only permits one read-only SELECT query")
        return await super().run_sql(args, context)


def create_demo_agent() -> Agent:
    _load_and_validate_env()

    database = os.environ["MYSQL_DATABASE"]
    # llm = OpenAILlmService(
    #     model=os.getenv("MODEL_NAME", "qwen-plus"),
    #     api_key=os.environ["DASHSCOPE_API_KEY"],
    #     base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    #     # DashScope is reachable directly on this machine. Ignore inherited
    #     # HTTP(S)_PROXY values, which otherwise cause the TLS handshake to time out.
    #     http_client=httpx.Client(
    #         trust_env=False,
    #         timeout=httpx.Timeout(60.0, connect=15.0),
    #     ),
    # )
    llm = OpenAILlmService(
        model=os.getenv("MODEL_NAME", "qwen-turbo"),
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url="https://ws-4y6jj5sl7n4cdp3r.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        http_client=httpx.Client(
            trust_env=False,
            timeout=httpx.Timeout(60.0, connect=15.0),
        ),
    )


    runner = ReadOnlyMySQLRunner(
        host=os.environ["MYSQL_HOST"],
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=database,
        charset="utf8mb4",
    )
    registry = ToolRegistry()
    registry.register_local_tool(
        RunSqlTool(
            sql_runner=runner,
            file_system=LocalFileSystem("./qwen_mysql_data"),
            custom_tool_description=(
                "Run one read-only MySQL SELECT query. To discover the schema, query "
                "information_schema.tables and information_schema.columns, filtering "
                f"table_schema = '{database}'."
            ),
        ),
        access_groups=["data_reader"],
    )

    prompt = f"""You are a careful MySQL data analyst for database `{database}`.
Answer the user in Chinese. You do not know the schema in advance.
Before answering a data question, use run_sql to inspect information_schema when needed,
then execute a read-only SELECT against the discovered tables and columns.
Never invent table names, column names, or query results. Never request or execute writes.
Keep result sets small with LIMIT unless aggregation returns only a few rows."""

    return Agent(
        llm_service=llm,
        tool_registry=registry,
        user_resolver=DemoUserResolver(),
        agent_memory=DemoAgentMemory(),
        system_prompt_builder=DefaultSystemPromptBuilder(base_prompt=prompt),
        config=AgentConfig(stream_responses=True),
    )
