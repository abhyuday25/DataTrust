"""Coordinates Phase 2 stages. Generated SQL stops at the unverified boundary."""

import json
import logging
import re
from time import perf_counter
from uuid import uuid4

from app.agents import PlannerAgent, RouterAgent, SQLAgent
from app.core import ApiError, Settings
from app.providers import ProviderError
from app.query_models import PipelineStage, QueryError, QueryMetadata, QueryRequest, QueryResponse, Route
from app.rag import RagIndex, context_for
from app.schemas import DatasetSchema
from app.service import DatasetService


class PipelineFailure(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message


def check_plan(plan, catalog: DatasetSchema, max_rows: int | None = None):
    table = catalog.table.name
    columns = {c.name for c in catalog.table.columns}
    if not plan.tables_needed or any(name != table for name in plan.tables_needed) or plan.joins:
        raise PipelineFailure('schema_grounding_failed', 'Plan refers to unavailable tables or joins')
    used = plan.dimensions + [m.field for m in plan.measures] + [f.field for f in plan.filters] + plan.group_by
    if any(name not in columns for name in used):
        raise PipelineFailure('schema_grounding_failed', 'Plan refers to unavailable columns')
    if max_rows is not None and plan.limit is not None and plan.limit > max_rows:
        raise PipelineFailure('plan_limit_exceeded', 'Plan exceeds requested row limit')


def check_generated(generated, catalog: DatasetSchema):
    table = catalog.table.name
    columns = {c.name for c in catalog.table.columns}
    sql = generated.sql.strip()
    if not re.match(r'^(SELECT|WITH)\b', sql, re.I) or ';' in sql.rstrip(';') or '```' in sql:
        raise PipelineFailure('sql_generation_failed', 'Generated SQL is not one analytical statement')
    if not generated.referenced_tables or any(name != table for name in generated.referenced_tables):
        raise PipelineFailure('schema_grounding_failed', 'SQL declares unavailable tables')
    for source in re.findall(r'\b(?:FROM|JOIN)\s+"?([A-Za-z_][A-Za-z0-9_]*)"?', sql, re.I):
        if source != table:
            raise PipelineFailure('schema_grounding_failed', 'SQL text refers to an unavailable table')
    for reference in generated.referenced_columns:
        parts = reference.split('.', 1)
        if len(parts) != 2 or parts[0] != table or parts[1] not in columns:
            raise PipelineFailure('schema_grounding_failed', 'SQL declares unavailable columns')
    # This is only a grounding check, not a SQL parser or permission to execute.


class QueryOrchestrator:
    def __init__(self, datasets: DatasetService, router: RouterAgent, planner: PlannerAgent, retriever: RagIndex, sql_agent: SQLAgent, settings: Settings):
        self.datasets, self.router, self.planner = datasets, router, planner
        self.retriever, self.sql_agent, self.settings = retriever, sql_agent, settings

    def run(self, request: QueryRequest, request_id: str | None = None) -> QueryResponse:
        if request.max_rows > self.settings.max_result_rows:
            raise ApiError(422, 'max_rows_exceeded', 'max_rows exceeds server limit')
        if not request.question.strip():
            raise ApiError(422, 'invalid_question', 'Question cannot be blank')
        catalog = self.datasets.schema(request.dataset_id)
        query_id = 'q_' + uuid4().hex
        stages: list[PipelineStage] = []
        started = perf_counter()
        response = QueryResponse(query_id=query_id, status='failed', metadata=QueryMetadata(latency_ms=0, stages=stages))

        def stage(name, action):
            begin = perf_counter()
            try:
                return action()
            except ProviderError as exc:
                if exc.code == 'malformed_provider_output':
                    label = {'routing': 'router', 'planning': 'planner', 'sql_generation': 'sql_agent'}.get(name, name)
                    raise PipelineFailure(f'malformed_{label}_output', 'AI provider returned invalid structured output') from None
                raise
            finally:
                duration = round((perf_counter() - begin) * 1000, 2)
                stages.append(PipelineStage(name=name, duration_ms=duration))
                logging.info(json.dumps({'event': 'query_stage', 'query_id': query_id, 'request_id': request_id, 'dataset_id': request.dataset_id, 'stage': name, 'duration_ms': duration}))

        try:
            route = stage('routing', lambda: self.router.run(request.question, query_id))
            response.route = route
            if route.route == Route.follow_up:
                response.status = 'needs_context'
                response.error = QueryError(code='conversation_unavailable', message='Follow-up questions need prior conversation context')
            elif route.route in (Route.unsupported, Route.general_question):
                response.status = 'unsupported'
                response.error = QueryError(code='unsupported_request', message='Ask a question about the selected dataset')
            elif route.route == Route.schema_question:
                evidence = stage('retrieval', lambda: self.retriever.retrieve(catalog, request.question, self.settings.rag_top_k))
                response.evidence = evidence
                response.answer = 'Columns in ' + catalog.dataset.name + ': ' + ', '.join(f'{c.name} ({c.dtype})' for c in catalog.table.columns[:100])
                response.status = 'completed'
            else:
                plan = stage('planning', lambda: self.planner.run(request.question, catalog, min(request.max_rows, self.settings.max_result_rows), query_id))
                response.plan = plan
                stage('validation', lambda: check_plan(plan, catalog, request.max_rows))
                retrieval_query = ' '.join([request.question, *plan.dimensions, *(m.field for m in plan.measures), *(f.field for f in plan.filters)])
                evidence = stage('retrieval', lambda: self.retriever.retrieve(catalog, retrieval_query, self.settings.rag_top_k))
                if not evidence.documents:
                    raise PipelineFailure('no_relevant_schema', 'No schema context could be retrieved')
                response.evidence = evidence
                logging.info(json.dumps({'event': 'query_evidence', 'query_id': query_id, 'dataset_id': request.dataset_id, 'documents': [{'id': d.document_id, 'score': d.score} for d in evidence.documents]}))
                generated = stage('sql_generation', lambda: self.sql_agent.run(request.question, plan, context_for(evidence), min(request.max_rows, self.settings.max_result_rows), query_id))
                response.sql = generated.sql
                stage('validation', lambda: check_generated(generated, catalog))
                response.validation = 'unverified'
                response.status = 'unverified'
        except ProviderError as exc:
            response.error = QueryError(code=exc.code, message='AI provider is unavailable or returned invalid output')
        except PipelineFailure as exc:
            if exc.code == 'schema_grounding_failed':
                response.validation = 'grounding_failed'
            response.error = QueryError(code=exc.code, message=exc.message)
        except (OSError, RuntimeError, ValueError):
            response.error = QueryError(code='retrieval_unavailable', message='Retrieval is unavailable')
        response.metadata = QueryMetadata(latency_ms=round((perf_counter() - started) * 1000, 2), stages=stages)
        logging.info(json.dumps({'event': 'query_finished', 'query_id': query_id, 'request_id': request_id, 'dataset_id': request.dataset_id, 'status': response.status, 'latency_ms': response.metadata.latency_ms}))
        return response
