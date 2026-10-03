"""Persist bounded query history, conversation plans, feedback, and materialized cache entries."""

import json
import math
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pydantic import BaseModel

from app.core import ApiError, Settings
from app.db import Database
from app.query_models import PlannerResult, QueryResponse
from app.schemas import DatasetSchema


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_question(question: str) -> str:
    return re.sub(r'\s+', ' ', question.strip()).casefold()


class ConversationState(BaseModel):
    last_question: str
    last_plan: PlannerResult
    last_sql: str
    result_columns: list[str]
    visualization: str | None = None


class StateStore:
    def __init__(self, db: Database, settings: Settings):
        self.db, self.settings = db, settings

    def save_query(self, user_id: str, dataset_id: str, question: str, response: QueryResponse):
        with self.db.connection() as con:
            con.execute('INSERT INTO query_records VALUES (?,?,?,?,?,?,?)',
                [response.query_id, user_id, dataset_id, question, response.status, _now(), response.model_dump_json()])

    def history(self, user_id: str, admin: bool, limit: int, offset: int, dataset_id: str | None, status: str | None):
        where = ['1=1']
        args = []
        if not admin:
            where.append('user_id=?'); args.append(user_id)
        if dataset_id:
            where.append('dataset_id=?'); args.append(dataset_id)
        if status:
            where.append('status=?'); args.append(status)
        with self.db.connection() as con:
            rows = con.execute(f'''SELECT id,dataset_id,question,status,created_at FROM query_records
                WHERE {' AND '.join(where)} ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?''', [*args, limit, offset]).fetchall()
        return [dict(zip(('query_id', 'dataset_id', 'question', 'status', 'created_at'), row)) for row in rows]

    def detail(self, query_id: str, user_id: str, admin: bool) -> dict:
        with self.db.connection() as con:
            row = con.execute('SELECT user_id,dataset_id,question,created_at,response_json FROM query_records WHERE id=?', [query_id]).fetchone()
        if not row or (not admin and row[0] != user_id):
            raise ApiError(404, 'not_found', 'Query not found')
        response = QueryResponse.model_validate_json(row[4])
        return {'dataset_id': row[1], 'question': row[2], 'created_at': row[3], 'response': response}

    def feedback(self, query_id: str, user_id: str, admin: bool, label: str, comment: str):
        self.detail(query_id, user_id, admin)
        with self.db.connection() as con:
            con.execute('INSERT INTO feedback VALUES (?,?,?,?,?)', [query_id, user_id, label, comment, _now()])

    def save_conversation(self, user_id: str, catalog: DatasetSchema, state: ConversationState, conversation_id: str | None = None) -> str:
        conversation_id = conversation_id or uuid4().hex
        with self.db.connection() as con:
            con.execute('DELETE FROM conversations WHERE id=? AND user_id=?', [conversation_id, user_id])
            con.execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?)', [conversation_id, user_id,
                catalog.dataset.id, catalog.dataset.version, catalog.dataset.schema_hash, state.model_dump_json(), _now()])
        return conversation_id

    def conversation(self, conversation_id: str, user_id: str, catalog: DatasetSchema) -> ConversationState:
        with self.db.connection() as con:
            row = con.execute('SELECT user_id,dataset_id,dataset_version,schema_hash,state_json FROM conversations WHERE id=?', [conversation_id]).fetchone()
        if not row or row[0] != user_id:
            raise ApiError(404, 'conversation_unavailable', 'Conversation not found')
        if (row[1], row[2], row[3]) != (catalog.dataset.id, catalog.dataset.version, catalog.dataset.schema_hash):
            raise ApiError(409, 'conversation_stale', 'Conversation dataset has changed')
        return ConversationState.model_validate_json(row[4])

    def cache_find(self, user_id: str, catalog: DatasetSchema, vector: list[float], model: str,
                   max_rows: int, visualize: bool) -> tuple[QueryResponse | None, str, float]:
        # ponytail: scan the newest 500 entries; add a dedicated vector index if cache volume grows.
        with self.db.connection() as con:
            rows = con.execute('''SELECT dataset_version,schema_hash,embedding_json,response_json,expires_at
                FROM cache_entries WHERE user_id=? AND dataset_id=? AND embedding_model=? AND max_rows=? AND visualize=?
                ORDER BY created_at DESC LIMIT 500''', [user_id, catalog.dataset.id, model, max_rows, visualize]).fetchall()
        best = None
        best_score = -1.0
        reason = 'miss'
        norm = math.sqrt(sum(x*x for x in vector))
        for version, schema_hash, encoded, response_json, expires_at in rows:
            if version != catalog.dataset.version or schema_hash != catalog.dataset.schema_hash:
                reason = 'stale'; continue
            if expires_at <= _now():
                reason = 'expired'; continue
            try:
                other = json.loads(encoded)
                if len(other) != len(vector) or norm == 0:
                    continue
                denom = norm * math.sqrt(sum(x*x for x in other))
                score = sum(a*b for a,b in zip(vector, other)) / denom if denom else -1
                response = QueryResponse.model_validate_json(response_json)
                if response.status != 'verified' or not response.result or not response.validation or response.validation.status != 'approved':
                    continue
            except (ValueError, TypeError, ZeroDivisionError):
                continue
            if score > best_score:
                best, best_score = response, score
        if best is not None and best_score >= self.settings.cache_similarity_threshold:
            return best, 'hit', best_score
        return None, reason, best_score

    def cache_store(self, user_id: str, catalog: DatasetSchema, question: str, vector: list[float],
                    model: str, max_rows: int, visualize: bool, response: QueryResponse):
        if response.status != 'verified' or not response.result:
            return
        now = _now()
        with self.db.connection() as con:
            con.execute('DELETE FROM cache_entries WHERE expires_at<=?', [now])
            con.execute('INSERT INTO cache_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', [uuid4().hex,
                user_id, catalog.dataset.id, catalog.dataset.version, catalog.dataset.schema_hash,
                normalize_question(question), model, json.dumps(vector), max_rows, visualize,
                response.model_dump_json(), now, now + timedelta(seconds=self.settings.cache_ttl_seconds)])
