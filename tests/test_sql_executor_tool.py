import time

import pytest

from vanna.tools import SQLExecutorTool


class FakeCursor:
    description = [("product",), ("amount",)]

    def __init__(self, rows, delay=0):
        self.rows = rows
        self.delay = delay

    def execute(self, sql):
        if self.delay:
            time.sleep(self.delay)
        if sql == "BROKEN":
            raise RuntimeError("Unknown column 'sales'")

    def fetchmany(self, size):
        return self.rows[:size]

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_returns_structured_rows():
    connection = FakeConnection(FakeCursor([("MacBook", 12999)]))
    tool = SQLExecutorTool(lambda: connection)

    result = await tool.run("SELECT product, amount FROM sales")

    assert result.success is True
    assert result.rows == [{"product": "MacBook", "amount": 12999}]
    assert result.columns == ["product", "amount"]
    assert connection.closed is True


@pytest.mark.asyncio
async def test_truncates_result_rows():
    tool = SQLExecutorTool(
        lambda: FakeConnection(FakeCursor([("a", 1), ("b", 2), ("c", 3)])),
        max_rows=2,
    )
    result = await tool.run("SELECT product, amount FROM sales")
    assert result.row_count == 2
    assert result.truncated is True


@pytest.mark.asyncio
async def test_captures_database_error():
    tool = SQLExecutorTool(lambda: FakeConnection(FakeCursor([])))
    result = await tool.run("BROKEN")
    assert result.success is False
    assert "Unknown column" in result.error


@pytest.mark.asyncio
async def test_reports_timeout():
    tool = SQLExecutorTool(
        lambda: FakeConnection(FakeCursor([], delay=0.1)),
        timeout_seconds=0.01,
    )
    result = await tool.run("SELECT 1")
    assert result.success is False
    assert "超过" in result.error
