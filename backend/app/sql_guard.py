"""One deterministic approval path for every generated and repaired query."""

from dataclasses import dataclass
from typing import Literal

import sqlglot
from pydantic import BaseModel, Field
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.qualify import qualify
from sqlglot.errors import OptimizeError

from app.schemas import DatasetSchema


class Check(BaseModel):
    name: str
    passed: bool


class Reason(BaseModel):
    code: str
    message: str


class ValidationResult(BaseModel):
    status: Literal['approved', 'rejected']
    checks: list[Check] = Field(default_factory=list)
    referenced_tables: list[str] = Field(default_factory=list)
    referenced_columns: list[str] = Field(default_factory=list)
    reasons: list[Reason] = Field(default_factory=list)


_APPROVAL = object()


@dataclass(frozen=True)
class ApprovedQuery:
    sql: str
    dataset_id: str
    validation: ValidationResult
    _approval: object


class SQLGuard:
    # Unknown UDFs and table functions are denied. These scalar/aggregate functions are useful analytics.
    SAFE_ANONYMOUS = {'date_trunc', 'strftime', 'strptime', 'year', 'month', 'day', 'date_part',
                      'coalesce', 'nullif', 'round', 'abs', 'lower', 'upper', 'trim', 'length',
                      'concat', 'count', 'sum', 'avg', 'min', 'max', 'median', 'quantile', 'ifnull'}

    def validate(self, sql: str, catalog: DatasetSchema) -> tuple[ValidationResult, ApprovedQuery | None]:
        result = ValidationResult(status='rejected')

        def fail(name: str, code: str, message: str):
            result.checks.append(Check(name=name, passed=False))
            result.reasons.append(Reason(code=code, message=message))
            return result, None

        try:
            statements = sqlglot.parse(sql, read='duckdb')
        except (ParseError, ValueError):
            return fail('parseable', 'SQL_SYNTAX_ERROR', 'SQL could not be parsed')
        if not statements or any(x is None for x in statements):
            return fail('parseable', 'SQL_SYNTAX_ERROR', 'SQL could not be parsed')
        result.checks.append(Check(name='parseable', passed=True))
        if len(statements) != 1:
            return fail('single_statement', 'MULTI_STATEMENT', 'Only one statement is allowed')
        result.checks.append(Check(name='single_statement', passed=True))
        tree = statements[0]
        if not isinstance(tree, exp.Select) or any(isinstance(node, (exp.DML, exp.DDL, exp.Command, exp.Into, exp.Union, exp.Intersect, exp.Except)) for node in tree.walk()):
            return fail('statement_allowlist', 'FORBIDDEN_STATEMENT', 'Only read-only SELECT queries are allowed')
        result.checks.append(Check(name='statement_allowlist', passed=True))
        ctes = {cte.alias for cte in tree.find_all(exp.CTE)}
        bases = []
        for table in tree.find_all(exp.Table):
            if isinstance(table.this, exp.Func):
                return fail('external_access', 'EXTERNAL_ACCESS', 'Table functions are not allowed')
            if table.db or table.catalog:
                return fail('table_allowlist', 'UNAUTHORIZED_TABLE', 'Only the selected dataset is available')
            name = table.name
            if name not in ctes:
                bases.append(name)
                if name != catalog.table.name:
                    return fail('table_allowlist', 'UNAUTHORIZED_TABLE', 'Only the selected dataset is available')
        if not bases:
            return fail('table_allowlist', 'UNAUTHORIZED_TABLE', 'Query must use the selected dataset')
        result.referenced_tables = sorted(set(bases))
        result.checks.append(Check(name='table_allowlist', passed=True))
        for func in tree.find_all(exp.Anonymous):
            if func.name.lower() not in self.SAFE_ANONYMOUS:
                return fail('external_access', 'FORBIDDEN_FUNCTION', 'Function is not allowed')
        # DuckDB can read files through quoted path tables; the exact catalog match above blocks them.
        result.checks.append(Check(name='external_access', passed=True))
        try:
            qualified = qualify(tree.copy(), dialect='duckdb',
                schema={catalog.table.name: {c.name: c.dtype for c in catalog.table.columns}},
                validate_qualify_columns=True)
        except (OptimizeError, ParseError, ValueError):
            return fail('column_allowlist', 'UNAUTHORIZED_COLUMN', 'Query references an unavailable or ambiguous column')
        result.referenced_columns = sorted({f'{col.table}.{col.name}' for col in qualified.find_all(exp.Column) if col.table == catalog.table.name})
        result.checks.append(Check(name='column_allowlist', passed=True))
        result.status = 'approved'
        return result, ApprovedQuery(sql, catalog.dataset.id, result, _APPROVAL)


def is_approved(query: ApprovedQuery) -> bool:
    return isinstance(query, ApprovedQuery) and query._approval is _APPROVAL and query.validation.status == 'approved'
