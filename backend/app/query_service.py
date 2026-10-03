"""Coordinates the verified query pipeline."""

import json
import logging
from time import perf_counter
from uuid import uuid4

from app.agents import PlannerAgent, RouterAgent, SQLAgent, RepairAgent, Synthesizer
from app.core import ApiError, Settings
from app.executor import ExecutionError, ReadOnlyExecutor
from app.providers import ProviderError
from app.query_models import PipelineStage, QueryError, QueryMetadata, QueryRequest, QueryResponse, Route
from app.rag import RagIndex, context_for
from app.result_ops import profile_result, plan_visualization
from app.schemas import DatasetSchema
from app.service import DatasetService
from app.sql_guard import SQLGuard


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


class QueryOrchestrator:
    def __init__(self, datasets: DatasetService, router: RouterAgent, planner: PlannerAgent, retriever: RagIndex, sql_agent: SQLAgent, settings: Settings):
        self.datasets, self.router, self.planner = datasets, router, planner
        self.retriever, self.sql_agent, self.settings = retriever, sql_agent, settings
        self.guard = SQLGuard()
        self.executor = ReadOnlyExecutor(settings.duckdb_path, settings.query_timeout_seconds)
        self.repair = RepairAgent(sql_agent.llm)
        self.synthesizer = Synthesizer(sql_agent.llm)

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
        repair_attempts = 0

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
            logging.info(json.dumps({'event': 'query_route', 'query_id': query_id, 'dataset_id': request.dataset_id, 'route': route.route.value}))
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
                for attempt in range(self.settings.max_repair_attempts + 1):
                    validation, approved = stage('validation', lambda: self.guard.validate(response.sql, catalog))
                    response.validation = validation
                    logging.info(json.dumps({'event': 'query_validation', 'query_id': query_id, 'dataset_id': request.dataset_id, 'attempt': attempt, 'status': validation.status, 'reason_codes': [reason.code for reason in validation.reasons]}))
                    if approved is None:
                        raise PipelineFailure(validation.reasons[0].code, validation.reasons[0].message)
                    try:
                        result = stage('execution', lambda: self.executor.execute(approved, min(request.max_rows, self.settings.max_result_rows)))
                        break
                    except ExecutionError as exc:
                        if not exc.repairable or attempt == self.settings.max_repair_attempts:
                            raise PipelineFailure(exc.code, 'Query execution failed safely') from None
                        repair_attempts += 1
                        logging.info(json.dumps({'event': 'query_repair', 'query_id': query_id, 'dataset_id': request.dataset_id, 'attempt': repair_attempts, 'error_code': exc.code}))
                        generated = stage('repair', lambda: self.repair.run(request.question, plan, context_for(evidence), response.sql, exc.code, repair_attempts))
                        response.sql = generated.sql
                response.result = result
                response.result_profile = stage('result_profiling', lambda: profile_result(result))
                synthesis = stage('synthesis', lambda: self.synthesizer.run(request.question, plan, response.sql, result, response.result_profile))
                response.answer, response.findings, response.assumptions = synthesis.answer, synthesis.findings, synthesis.assumptions
                response.visualization = stage('visualization', lambda: plan_visualization(result, response.result_profile, request.visualize or route.requires_visualization))
                response.status = 'verified'
        except ProviderError as exc:
            response.error = QueryError(code=exc.code, message='AI provider is unavailable or returned invalid output')
        except PipelineFailure as exc:
            response.error = QueryError(code=exc.code, message=exc.message)
        except (OSError, RuntimeError, ValueError):
            response.error = QueryError(code='retrieval_unavailable', message='Retrieval is unavailable')
        response.metadata = QueryMetadata(latency_ms=round((perf_counter() - started) * 1000, 2), stages=stages, repair_attempts=repair_attempts)
        logging.info(json.dumps({'event': 'query_finished', 'query_id': query_id, 'request_id': request_id, 'dataset_id': request.dataset_id, 'status': response.status, 'latency_ms': response.metadata.latency_ms}))
        return response
