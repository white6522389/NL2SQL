"""FastAPI entrypoint for the five-agent NL2SQL application."""

import asyncio
import json
import os
import uuid
from pathlib import Path

import httpx
import pymysql
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from vanna.agents.nl2sql import (
    AnalysisVisualizationAgent,
    NL2SQLWorkflow,
    PlannerAgent,
    ReflectionAgent,
    SQLAgent,
    SQLValidatorAgent,
)
from vanna.agents.nl2sql.observability import ObservedLlmService, TraceCollector
from vanna.agents.nl2sql.conversation_memory import ConversationMemoryStore
from vanna.integrations.openai import OpenAILlmService
from vanna.services import MySQLSchemaRepository
from vanna.tools import SQLExecutorTool

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=100)


conversation_memory = ConversationMemoryStore()


def mysql_connection():
    return pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=20,
    )


def create_workflow() -> NL2SQLWorkflow:
    trace = TraceCollector()
    client = httpx.Client(trust_env=False, timeout=httpx.Timeout(60, connect=15))
    base_llm = OpenAILlmService(
        model=os.getenv("MODEL_NAME", "qwen-turbo"),
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://ws-4y6jj5sl7n4cdp3r.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        ),
        http_client=client,
    )
    llm = ObservedLlmService(base_llm, trace)
    repository = MySQLSchemaRepository(os.environ["MYSQL_DATABASE"], mysql_connection)
    return NL2SQLWorkflow(
        PlannerAgent(llm),
        SQLAgent(llm),
        SQLValidatorAgent(),
        SQLExecutorTool(mysql_connection, timeout_seconds=20, max_rows=500),
        ReflectionAgent(llm),
        AnalysisVisualizationAgent(llm),
        repository,
        max_retries=2,
        trace=trace,
    )


app = FastAPI(title="智能数据分析 NL2SQL 平台", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "healthy", "database": os.getenv("MYSQL_DATABASE", "")}


@app.post("/api/analyze")
async def analyze(request: AnalyzeRequest):
    conversation_id = request.conversation_id or uuid.uuid4().hex
    previous_state = conversation_memory.get(conversation_id)
    conversation_context = (
        previous_state.as_planner_context() if previous_state else None
    )

    async def stream():
        queue = asyncio.Queue()

        async def on_event(event):
            await queue.put({"type": "stage", "data": event.model_dump(mode="json")})

        async def execute():
            try:
                result = await create_workflow().run(
                    request.question,
                    on_event,
                    conversation_context=conversation_context,
                )
                result.conversation_id = conversation_id
                if result.success:
                    conversation_memory.save(conversation_id, request.question, result)
                await queue.put({"type": "result", "data": result.model_dump(mode="json")})
            except Exception as exc:
                await queue.put({"type": "error", "data": {"message": str(exc)}})
            finally:
                await queue.put(None)

        task = asyncio.create_task(execute())
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False, default=str)}\n\n"
        await task
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
