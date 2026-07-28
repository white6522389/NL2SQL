"""Structured state models shared by the NL2SQL agents."""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class TaskType(str, Enum):
    """Top-level route selected by the planner."""

    SQL_QUERY = "sql_query"
    GENERAL_QUESTION = "general_question"
    CLARIFICATION = "clarification"


class TaskPlan(BaseModel):
    """Validated execution plan produced before SQL generation."""

    task_type: TaskType
    need_database_query: bool
    need_visualization: bool
    objective: str = Field(min_length=1)
    analysis_type: Optional[str] = None
    time_range: Optional[str] = None
    filters: Dict[str, str] = Field(default_factory=dict)
    execution_steps: List[str] = Field(min_length=1)


class SchemaColumn(BaseModel):
    """Column metadata used as grounding context for SQL generation."""

    name: str
    data_type: str
    nullable: bool = True
    comment: str = ""
    key: str = ""
    referenced_table: Optional[str] = None
    referenced_column: Optional[str] = None
    sample_values: List[str] = Field(default_factory=list)


class SchemaTable(BaseModel):
    """Database table and its documented columns."""

    name: str
    comment: str = ""
    columns: List[SchemaColumn] = Field(default_factory=list)


class SchemaCatalog(BaseModel):
    """Complete schema snapshot loaded from MySQL."""

    database: str
    tables: List[SchemaTable] = Field(default_factory=list)


class SchemaContext(BaseModel):
    """Relevant subset retrieved for one user request."""

    database: str
    tables: List[SchemaTable] = Field(default_factory=list)

    def as_prompt(self) -> str:
        """Render deterministic schema grounding text for an LLM."""
        sections = [f"Database: `{self.database}`"]
        for table in self.tables:
            header = f"Table `{table.name}`"
            if table.comment:
                header += f": {table.comment}"
            lines = [header]
            for column in table.columns:
                details = [column.data_type]
                if column.key:
                    details.append(column.key)
                if not column.nullable:
                    details.append("NOT NULL")
                if column.comment:
                    details.append(column.comment)
                if column.referenced_table and column.referenced_column:
                    details.append(
                        f"FK -> {column.referenced_table}.{column.referenced_column}"
                    )
                if column.sample_values:
                    values = ", ".join(repr(value) for value in column.sample_values)
                    details.append(f"actual values: {values}")
                lines.append(f"- `{column.name}`: {', '.join(details)}")
            sections.append("\n".join(lines))
        return "\n\n".join(sections)


class SQLCandidate(BaseModel):
    """SQL produced by SQL Agent and awaiting validation in Task 4."""

    sql: str = Field(min_length=1)
    referenced_tables: List[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    """Result returned by SQL Validator Agent."""

    valid: bool
    reason: Optional[str] = None
    error_type: Optional[str] = None
    suggestion: Optional[str] = None
    referenced_tables: List[str] = Field(default_factory=list)
    referenced_columns: List[str] = Field(default_factory=list)


class ExecutionResult(BaseModel):
    """Structured, JSON-safe result returned by SQL Executor Tool."""

    success: bool
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    columns: List[str] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    elapsed_ms: float = 0.0
    error: Optional[str] = None


class ReflectionResult(BaseModel):
    error_type: str
    error: str
    suggestion: str
    retryable: bool = True


class ChartConfig(BaseModel):
    """Frontend-neutral chart description convertible to ECharts options."""

    type: str
    title: str = ""
    x_field: Optional[str] = None
    y_field: Optional[str] = None
    name_field: Optional[str] = None
    value_field: Optional[str] = None
    data: List[Dict[str, Any]] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    summary: str
    insights: List[str] = Field(default_factory=list)
    chart: Optional[ChartConfig] = None

    @field_validator("insights", mode="before")
    @classmethod
    def normalize_insights(cls, value: Any) -> Any:
        """Accept a single insight string returned by less strict LLMs."""
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return value


class WorkflowEvent(BaseModel):
    stage: str
    status: str
    message: str
    trace_id: Optional[str] = None
    elapsed_ms: Optional[float] = None


class WorkflowMetrics(BaseModel):
    trace_id: str
    total_elapsed_ms: float
    stage_timings_ms: Dict[str, float] = Field(default_factory=dict)
    llm_call_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    retry_count: int = 0


class WorkflowResult(BaseModel):
    success: bool
    conversation_id: Optional[str] = None
    plan: TaskPlan
    schema_context: SchemaContext
    sql: Optional[str] = None
    validation: Optional[ValidationResult] = None
    execution: Optional[ExecutionResult] = None
    reflections: List[ReflectionResult] = Field(default_factory=list)
    analysis: Optional[AnalysisResult] = None
    metrics: Optional[WorkflowMetrics] = None
    error: Optional[str] = None
