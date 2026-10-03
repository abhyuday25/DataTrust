"""Dedicated read-only DuckDB execution for approved analytical SQL."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from threading import Event, Thread
from time import perf_counter

import duckdb
from pydantic import BaseModel

from app.sql_guard import ApprovedQuery, is_approved


class ExecutionError(Exception):
    def __init__(self, code: str, repairable: bool = False):
        self.code, self.repairable = code, repairable
        super().__init__(code)


class ExecutionResult(BaseModel):
    columns: list[str]
    rows: list[list[object]]
    row_count: int
    truncated: bool
    duration_ms: float


def _safe_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return value


class ReadOnlyExecutor:
    def __init__(self, path: Path, timeout_seconds: int):
        self.path, self.timeout_seconds = path, timeout_seconds

    def execute(self, query: ApprovedQuery, max_rows: int) -> ExecutionResult:
        if not is_approved(query) or max_rows < 1:
            raise ExecutionError('POLICY_REJECTION')
        started = perf_counter()
        done = Event()
        state = {}

        def work():
            con = None
            try:
                con = duckdb.connect(str(self.path), read_only=True)
                state['connection'] = con
                con.execute('SET enable_external_access=false')
                # Wrapping caps both delivery and fetch work even when the model omitted LIMIT.
                cursor = con.execute(f'SELECT * FROM ({query.sql.rstrip().rstrip(";")}) AS verified_result LIMIT {max_rows + 1}')
                columns = [item[0] for item in cursor.description]
                rows = cursor.fetchmany(max_rows + 1)
                state['result'] = ExecutionResult(columns=columns,
                    rows=[[_safe_value(v) for v in row] for row in rows[:max_rows]],
                    row_count=min(len(rows), max_rows), truncated=len(rows) > max_rows,
                    duration_ms=round((perf_counter() - started) * 1000, 2))
            except duckdb.Error as exc:
                name = type(exc).__name__.lower()
                detail = str(exc).lower()
                code = ('AGGREGATION_ERROR' if 'aggregate' in detail and 'group' in detail else
                        'TYPE_ERROR' if 'no function matches' in detail or 'conversion' in name or 'type' in name else
                        'SCHEMA_ERROR' if 'binder' in name or 'catalog' in name else
                        'SQL_SYNTAX_ERROR' if 'parser' in name else 'EXECUTION_ERROR')
                state['error'] = ExecutionError(code, code in {'SCHEMA_ERROR', 'TYPE_ERROR', 'AGGREGATION_ERROR', 'SQL_SYNTAX_ERROR'})
            finally:
                if con is not None:
                    con.close()
                done.set()

        thread = Thread(target=work, daemon=True)
        thread.start()
        if not done.wait(self.timeout_seconds):
            con = state.get('connection')
            if con is not None:
                con.interrupt()
            done.wait(1)
            raise ExecutionError('TIMEOUT')
        if 'error' in state:
            raise state['error']
        return state['result']
