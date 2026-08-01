"""Standalone MCP entrypoint for the NL2SQL application."""

import argparse
import os

from backend.app import ROOT, create_workflow, mysql_connection
from dotenv import load_dotenv

from vanna.integrations.mcp import create_nl2sql_mcp_server
from vanna.services import MySQLSchemaRepository
from vanna.tools import SQLExecutorTool

load_dotenv(ROOT / ".env", override=False)


def build_server(host: str = "127.0.0.1", port: int = 8001):
    repository = MySQLSchemaRepository(os.environ["MYSQL_DATABASE"], mysql_connection)
    executor = SQLExecutorTool(mysql_connection, timeout_seconds=20, max_rows=500)
    return create_nl2sql_mcp_server(
        create_workflow,
        repository,
        executor,
        host=host,
        port=port,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Vanna NL2SQL MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    build_server(args.host, args.port).run(transport=args.transport)


if __name__ == "__main__":
    main()
