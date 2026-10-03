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
    name: Literal['routing', 'planning', 'retrieval', 'sql_generation', 'validation', 'execution', 'completed', 'failed']
    duration_ms: float


class QueryMetadata(StrictModel):
    latency_ms: float
    stages: list[PipelineStage]
    cache_hit: bool = False


class QueryError(StrictModel):
    code: str
    message: str


class QueryResponse(StrictModel):
    query_id: str
    status: Literal['unverified', 'completed', 'failed', 'needs_context', 'unsupported']
    route: RouterResult | None = None
    plan: PlannerResult | None = None
    answer: str | None = None
    sql: str | None = None
    validation: Literal['unverified', 'grounding_failed'] | None = None
    result: None = None  # Phase 2 never executes generated SQL.
    evidence: RetrievalResult | None = None
    error: QueryError | None = None
    metadata: QueryMetadata
