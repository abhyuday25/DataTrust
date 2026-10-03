from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ColumnProfile(BaseModel):
    null_count: int
    null_percentage: float
    distinct_count: int
    minimum: Any | None = None
    maximum: Any | None = None
    samples: list[Any]


class ColumnMetadata(BaseModel):
    name: str
    dtype: str
    description: str | None = None
    profile: ColumnProfile | None = None


class DatasetSummary(BaseModel):
    id: str
    name: str
    version: str
    schema_hash: str
    row_count: int
    created_at: datetime
    updated_at: datetime


class TableMetadata(BaseModel):
    name: str
    description: str | None = None
    row_count: int
    columns: list[ColumnMetadata]


class DatasetSchema(BaseModel):
    dataset: DatasetSummary
    table: TableMetadata
    warnings: list[str]
