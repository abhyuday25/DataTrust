from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Route(str, Enum):
    analytics_query = 'analytics_query'
    schema_question = 'schema_question'
    general_question = 'general_question'
    follow_up = 'follow_up'
    unsupported = 'unsupported'


class RouterResult(StrictModel):
    route: Route
    requires_database: bool
    requires_visualization: bool
    confidence: float = Field(ge=0, le=1)


class Measure(StrictModel):
    field: str
    aggregation: str


class Filter(StrictModel):
    field: str
    operator: str
    value: str | int | float | bool | None


class Join(StrictModel):
    left_table: str
    left_column: str
    right_table: str
    right_column: str


class OrderBy(StrictModel):
    field: str
    direction: Literal['ASC', 'DESC']


class PlannerResult(StrictModel):
    objective: str
    tables_needed: list[str]
    dimensions: list[str]
    measures: list[Measure]
    filters: list[Filter]
    joins: list[Join]
    group_by: list[str]
    order_by: list[OrderBy]
    limit: int | None = Field(default=None, ge=1)
    visualization: str | None = None
    assumptions: list[str]


class GeneratedSQL(StrictModel):
    sql: str = Field(min_length=1)
    referenced_tables: list[str]
    referenced_columns: list[str]
    assumptions: list[str]


class MetadataDocument(StrictModel):
    document_id: str
    dataset_id: str
    dataset_version: str
    schema_hash: str
    object_type: Literal['table', 'column']
    table_name: str
    column_name: str | None = None
    content: str


class RetrievedDocument(StrictModel):
    document_id: str
    object_type: str
    table_name: str
    column_name: str | None
    score: float
    content: str


class RetrievalResult(StrictModel):
    dataset_id: str
    documents: list[RetrievedDocument]


class QueryRequest(StrictModel):
    dataset_id: str = Field(min_length=1, max_length=64, pattern=r'^[a-f0-9]+$')
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    visualize: bool = False
    max_rows: int = Field(default=1000, ge=1)


class PipelineStage(StrictModel):
    name: Literal['routing', 'planning', 'retrieval', 'sql_generation', 'validation', 'execution', 'repair', 'result_profiling', 'synthesis', 'visualization', 'completed', 'failed']
    duration_ms: float


class QueryMetadata(StrictModel):
    latency_ms: float
    stages: list[PipelineStage]
    cache_hit: bool = False
    repair_attempts: int = 0


class QueryError(StrictModel):
    code: str
    message: str


class ResultColumnProfile(StrictModel):
    name: str
    type: str
    role: Literal['dimension', 'measure', 'temporal']
    distinct_count: int
    null_count: int
    minimum: float | None = None
    maximum: float | None = None


class ResultProfile(StrictModel):
    row_count: int
    columns: list[ResultColumnProfile]


class Visualization(StrictModel):
    type: Literal['kpi', 'bar', 'line', 'scatter', 'table']
    x: str | None = None
    y: str | None = None
    value: str | None = None


class Synthesis(StrictModel):
    answer: str
    findings: list[str]
    assumptions: list[str]


class QueryResponse(StrictModel):
    query_id: str
    status: Literal['verified', 'completed', 'failed', 'needs_context', 'unsupported']
    route: RouterResult | None = None
    plan: PlannerResult | None = None
    answer: str | None = None
    sql: str | None = None
    validation: 'ValidationResult | None' = None
    result: 'ExecutionResult | None' = None
    result_profile: ResultProfile | None = None
    visualization: Visualization | None = None
    findings: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    evidence: RetrievalResult | None = None
    error: QueryError | None = None
    metadata: QueryMetadata


from app.executor import ExecutionResult
from app.sql_guard import ValidationResult
QueryResponse.model_rebuild()
