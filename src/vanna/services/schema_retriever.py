"""MySQL schema knowledge ingestion and query-focused retrieval."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

from vanna.agents.nl2sql.models import (
    SchemaCatalog,
    SchemaColumn,
    SchemaContext,
    SchemaTable,
)


class MySQLSchemaRepository:
    """Build a schema catalog from MySQL information_schema metadata."""

    def __init__(
        self,
        database: str,
        connection_factory: Callable[[], Any],
        sample_value_limit: int = 20,
        sample_column_limit: int = 30,
    ):
        self.database = database
        self.connection_factory = connection_factory
        self.sample_value_limit = sample_value_limit
        self.sample_column_limit = sample_column_limit

    def load(self) -> SchemaCatalog:
        connection = self.connection_factory()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """SELECT TABLE_NAME, TABLE_COMMENT
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
                ORDER BY TABLE_NAME""",
                (self.database,),
            )
            table_rows = cursor.fetchall()

            cursor.execute(
                """SELECT c.TABLE_NAME, c.COLUMN_NAME, c.COLUMN_TYPE,
                          c.IS_NULLABLE, c.COLUMN_KEY, c.COLUMN_COMMENT,
                          k.REFERENCED_TABLE_NAME, k.REFERENCED_COLUMN_NAME
                FROM information_schema.COLUMNS c
                LEFT JOIN information_schema.KEY_COLUMN_USAGE k
                  ON k.TABLE_SCHEMA = c.TABLE_SCHEMA
                 AND k.TABLE_NAME = c.TABLE_NAME
                 AND k.COLUMN_NAME = c.COLUMN_NAME
                 AND k.REFERENCED_TABLE_NAME IS NOT NULL
                WHERE c.TABLE_SCHEMA = %s
                ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION""",
                (self.database,),
            )
            column_rows = cursor.fetchall()

            sample_values: Dict[tuple[str, str], List[str]] = {}
            text_columns = [
                row
                for row in column_rows
                if self._is_safe_categorical_column(
                    row["COLUMN_NAME"], row["COLUMN_TYPE"]
                )
            ][: self.sample_column_limit]
            for row in text_columns:
                table = self._quote_identifier(row["TABLE_NAME"])
                column = self._quote_identifier(row["COLUMN_NAME"])
                try:
                    cursor.execute(
                        f"SELECT {column} AS value, COUNT(*) AS frequency "
                        f"FROM {self._quote_identifier(self.database)}.{table} "
                        f"WHERE {column} IS NOT NULL AND {column} <> '' "
                        f"GROUP BY {column} ORDER BY frequency DESC "
                        f"LIMIT {int(self.sample_value_limit) + 1}"
                    )
                    values = [
                        str(value_row["value"]) for value_row in cursor.fetchall()
                    ]
                    sample_values[(row["TABLE_NAME"], row["COLUMN_NAME"])] = (
                        values if len(values) <= self.sample_value_limit else []
                    )
                except Exception:
                    # Sampling is optional; metadata retrieval must remain available.
                    sample_values[(row["TABLE_NAME"], row["COLUMN_NAME"])] = []
            cursor.close()
        finally:
            connection.close()

        columns_by_table: Dict[str, List[SchemaColumn]] = defaultdict(list)
        for row in column_rows:
            columns_by_table[row["TABLE_NAME"]].append(
                SchemaColumn(
                    name=row["COLUMN_NAME"],
                    data_type=row["COLUMN_TYPE"],
                    nullable=row["IS_NULLABLE"] == "YES",
                    key=row.get("COLUMN_KEY") or "",
                    comment=row.get("COLUMN_COMMENT") or "",
                    referenced_table=row.get("REFERENCED_TABLE_NAME"),
                    referenced_column=row.get("REFERENCED_COLUMN_NAME"),
                    sample_values=sample_values.get(
                        (row["TABLE_NAME"], row["COLUMN_NAME"]), []
                    ),
                )
            )

        return SchemaCatalog(
            database=self.database,
            tables=[
                SchemaTable(
                    name=row["TABLE_NAME"],
                    comment=row.get("TABLE_COMMENT") or "",
                    columns=columns_by_table.get(row["TABLE_NAME"], []),
                )
                for row in table_rows
            ],
        )

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        return f"`{str(identifier).replace('`', '``')}`"

    @staticmethod
    def _is_safe_categorical_column(column_name: str, column_type: str) -> bool:
        """Avoid sending free-form or personally identifying values to the LLM."""
        data_type = str(column_type).lower()
        if data_type.startswith("enum"):
            return True
        if not data_type.startswith(("varchar", "char")):
            return False
        name = str(column_name).lower()
        safe_markers = (
            "region",
            "category",
            "status",
            "type",
            "gender",
            "city",
            "country",
            "province",
            "state",
        )
        return any(marker in name for marker in safe_markers)


class SchemaRetriever:
    """Retrieve relevant tables using names, comments, fields, and relationships."""

    def __init__(self, catalog: SchemaCatalog):
        self.catalog = catalog

    def retrieve(self, query: str, top_k: int = 5) -> SchemaContext:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        query_terms = self._terms(query)
        scored = []
        for table in self.catalog.tables:
            document = " ".join(
                [table.name, table.comment]
                + [f"{column.name} {column.comment}" for column in table.columns]
            )
            score = len(query_terms & self._terms(document))
            scored.append((score, table.name, table))

        scored.sort(key=lambda item: (-item[0], item[1]))
        selected = [item[2] for item in scored if item[0] > 0][:top_k]
        if not selected:
            selected = [item[2] for item in scored[:top_k]]

        # Include directly related tables so joins have both sides of an FK.
        selected_names = {table.name for table in selected}
        related_names: Set[str] = set()
        for table in self.catalog.tables:
            for column in table.columns:
                if table.name in selected_names and column.referenced_table:
                    related_names.add(column.referenced_table)
                if column.referenced_table in selected_names:
                    related_names.add(table.name)
        for table in self.catalog.tables:
            if table.name in related_names and table.name not in selected_names:
                selected.append(table)
                selected_names.add(table.name)

        return SchemaContext(database=self.catalog.database, tables=selected)

    @staticmethod
    def _terms(text: str) -> Set[str]:
        normalized = text.lower()
        words = set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", normalized))
        chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
        bigrams: Iterable[str] = (
            chinese[index : index + 2] for index in range(max(0, len(chinese) - 1))
        )
        return words | set(bigrams)
