"""Deterministic SQL Validator Agent for MySQL 5.7 read-only queries."""

from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple

import sqlparse
from sqlparse.tokens import DML

from .models import SchemaCatalog, ValidationResult


class SQLValidatorAgent:
    """Validate SQL syntax shape, schema references, and read-only safety."""

    _dangerous = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|RENAME|"
        r"GRANT|REVOKE|CALL|EXECUTE|HANDLER|LOAD|LOCK|UNLOCK|INTO\s+OUTFILE|"
        r"INTO\s+DUMPFILE)\b",
        re.IGNORECASE,
    )
    _table_ref = re.compile(
        r"\b(?:FROM|JOIN)\s+`?([A-Za-z_][\w$]*)`?(?:\s+(?:AS\s+)?"
        r"(?!WHERE\b|JOIN\b|LEFT\b|RIGHT\b|INNER\b|OUTER\b|FULL\b|CROSS\b|"
        r"ON\b|GROUP\b|ORDER\b|LIMIT\b|HAVING\b)([A-Za-z_][\w$]*))?",
        re.IGNORECASE,
    )
    _qualified_column = re.compile(
        r"\b([A-Za-z_][\w$]*)\s*\.\s*`?([A-Za-z_][\w$]*|\*)`?"
    )
    _string_equality = re.compile(
        r"(?:(?P<qualifier>[A-Za-z_][\w$]*)\s*\.\s*)?"
        r"`?(?P<column>[A-Za-z_][\w$]*)`?\s*=\s*"
        r"(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
        re.IGNORECASE,
    )

    def validate(self, sql: str, schema: SchemaCatalog) -> ValidationResult:
        normalized = sql.strip()
        if not normalized:
            return ValidationResult(valid=False, reason="SQL不能为空")
        if "--" in normalized or "/*" in normalized or "#" in normalized:
            return ValidationResult(valid=False, reason="禁止在SQL中使用注释")

        statements = [item for item in sqlparse.parse(normalized) if str(item).strip()]
        if len(statements) != 1:
            return ValidationResult(valid=False, reason="只允许执行单条SQL")
        statement = statements[0]
        first = statement.token_first(skip_cm=True, skip_ws=True)
        if first is None or first.ttype is not DML or first.normalized != "SELECT":
            return ValidationResult(valid=False, reason="只允许执行SELECT查询")
        if self._dangerous.search(normalized):
            return ValidationResult(valid=False, reason="禁止执行危险SQL")
        if re.search(r"\bCROSS\s+JOIN\b", normalized, re.IGNORECASE):
            return ValidationResult(
                valid=False,
                reason="禁止CROSS JOIN，可能产生笛卡尔积",
                error_type="unsafe_join",
                suggestion="请使用带ON关联条件的INNER JOIN或LEFT JOIN",
            )
        if not re.search(r"\bFROM\b", normalized, re.IGNORECASE):
            return ValidationResult(valid=False, reason="SELECT查询缺少FROM子句")

        table_map = {table.name.lower(): table for table in schema.tables}
        table_refs, aliases = self._extract_tables(normalized)
        if not table_refs:
            return ValidationResult(valid=False, reason="无法识别查询表")
        unknown_tables = [name for name in table_refs if name.lower() not in table_map]
        if unknown_tables:
            return ValidationResult(
                valid=False, reason=f"表不存在: {', '.join(unknown_tables)}"
            )

        referenced_columns: List[str] = []
        for qualifier, column in self._qualified_column.findall(normalized):
            if column == "*":
                continue
            table_name = aliases.get(qualifier.lower(), qualifier.lower())
            table = table_map.get(table_name)
            if table is None:
                return ValidationResult(valid=False, reason=f"未知表别名: {qualifier}")
            known_columns = {item.name.lower() for item in table.columns}
            if column.lower() not in known_columns:
                return ValidationResult(
                    valid=False,
                    reason=f"字段不存在: {table.name}.{column}",
                    referenced_tables=table_refs,
                )
            referenced_columns.append(f"{table.name}.{column}")

        semantic_error = self._validate_categorical_values(
            normalized, table_refs, aliases, table_map
        )
        if semantic_error:
            return semantic_error

        return ValidationResult(
            valid=True,
            referenced_tables=table_refs,
            referenced_columns=sorted(set(referenced_columns)),
        )

    def _extract_tables(self, sql: str) -> Tuple[List[str], Dict[str, str]]:
        tables: List[str] = []
        aliases: Dict[str, str] = {}
        for table, alias in self._table_ref.findall(sql):
            if table not in tables:
                tables.append(table)
            aliases[table.lower()] = table.lower()
            if alias:
                aliases[alias.lower()] = table.lower()
        return tables, aliases

    def _validate_categorical_values(
        self,
        sql: str,
        table_refs: List[str],
        aliases: Dict[str, str],
        table_map: Dict[str, object],
    ) -> ValidationResult | None:
        selected_tables = [table_map[name.lower()] for name in table_refs]
        for match in self._string_equality.finditer(sql):
            column_name = match.group("column")
            value = match.group("value")
            qualifier = match.group("qualifier")
            if qualifier:
                table_name = aliases.get(qualifier.lower(), qualifier.lower())
                candidates = [table_map.get(table_name)]
            else:
                candidates = [
                    table
                    for table in selected_tables
                    if column_name.lower()
                    in {column.name.lower() for column in table.columns}
                ]
            candidates = [table for table in candidates if table is not None]
            if len(candidates) != 1:
                continue
            table = candidates[0]
            column = next(
                (
                    item
                    for item in table.columns
                    if item.name.lower() == column_name.lower()
                ),
                None,
            )
            if not column or not column.sample_values or value in column.sample_values:
                continue
            allowed = "、".join(column.sample_values)
            return ValidationResult(
                valid=False,
                reason=f"{table.name}.{column.name}不存在取值“{value}”",
                error_type="invalid_enum_value",
                suggestion=f"请使用真实取值之一：{allowed}",
                referenced_tables=table_refs,
            )
        return None
