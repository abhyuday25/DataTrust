"""Bounded result descriptions and deterministic chart selection."""

import re

from app.executor import ExecutionResult
from app.query_models import ResultColumnProfile, ResultProfile, Visualization


def profile_result(result: ExecutionResult) -> ResultProfile:
    columns = []
    for index, name in enumerate(result.columns):
        values = [row[index] for row in result.rows if row[index] is not None]
        numeric = bool(values) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)
        temporal = bool(values) and all(isinstance(v, str) and re.match(r'^\d{4}-\d{2}-\d{2}', v) for v in values)
        role = 'measure' if numeric else 'temporal' if temporal else 'dimension'
        columns.append(ResultColumnProfile(name=name, type=type(values[0]).__name__ if values else 'unknown',
            role=role, distinct_count=len({str(v) for v in values}), null_count=result.row_count - len(values),
            minimum=min(values) if numeric else None, maximum=max(values) if numeric else None))
    return ResultProfile(row_count=result.row_count, columns=columns)


def plan_visualization(result: ExecutionResult, profile: ResultProfile, requested: bool) -> Visualization:
    if not requested or not result.rows:
        return Visualization(type='table')
    measures = [c.name for c in profile.columns if c.role == 'measure']
    temporal = [c.name for c in profile.columns if c.role == 'temporal']
    dimensions = [c.name for c in profile.columns if c.role == 'dimension']
    if result.row_count == 1 and len(result.columns) == 1 and measures:
        return Visualization(type='kpi', value=measures[0])
    if temporal and measures:
        return Visualization(type='line', x=temporal[0], y=measures[0])
    if len(measures) >= 2 and len(result.columns) == 2:
        return Visualization(type='scatter', x=measures[0], y=measures[1])
    if len(dimensions) == 1 and measures and len(result.columns) == 2 and result.row_count <= 50:
        return Visualization(type='bar', x=dimensions[0], y=measures[0])
    return Visualization(type='table')
