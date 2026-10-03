import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents import PlannerAgent, RouterAgent, SQLAgent
from app.core import Settings, create_app
from app.providers import OllamaProvider, ProviderError
from app.query_models import GeneratedSQL, PlannerResult, Route, RouterResult, Synthesis
from app.query_service import PipelineFailure, QueryOrchestrator, check_plan
from app.sql_guard import SQLGuard
from app.rag import RagIndex, catalog_documents


class FakeLLM:
    def __init__(self, table: str):
        self.table = table
        self.calls = []

    def generate_structured(self, system, user, output):
        self.calls.append(output.__name__)
        if output is RouterResult:
            route = Route.schema_question if 'columns' in user.lower() else Route.analytics_query
            return RouterResult(route=route, requires_database=route == Route.analytics_query, requires_visualization=False, confidence=.9)
        if output is PlannerResult:
            return PlannerResult(objective='Top regions by revenue', tables_needed=[self.table], dimensions=['region'], measures=[{'field': 'revenue', 'aggregation': 'SUM'}], filters=[], joins=[], group_by=['region'], order_by=[{'field': 'total_revenue', 'direction': 'DESC'}], limit=5, assumptions=[])
        if output is Synthesis:
            return Synthesis(answer='North has 12.5 and South has 7.0.', findings=[], assumptions=[])
        return GeneratedSQL(sql=f'SELECT region, SUM(revenue) AS total_revenue FROM "{self.table}" GROUP BY region ORDER BY total_revenue DESC LIMIT 5', referenced_tables=[self.table], referenced_columns=[f'{self.table}.region', f'{self.table}.revenue'], assumptions=[])


class FakeEmbeddings:
    model = 'fake-4d'

    def embed_batch(self, texts):
        return [[1, text.lower().count('revenue'), text.lower().count('region'), text.lower().count('order_date') + text.lower().count('2025') + text.lower().count('monthly')] for text in texts]


def fixture(tmp_path):
    settings = Settings(duckdb_path=tmp_path / 'data.duckdb', data_dir=tmp_path / 'uploads', faiss_index_path=tmp_path / 'faiss', rag_top_k=4)
    app = create_app(settings)
    client = TestClient(app)
    uploaded = client.post('/api/datasets/upload', files={'file': ('sales.csv', b'order_id,region,revenue,order_date\n1,North,12.5,2025-01-01\n2,South,7.0,2025-02-01\n')})
    assert uploaded.status_code == 201, uploaded.text
    catalog = app.state.datasets.schema(uploaded.json()['dataset']['id'])
    fake = FakeLLM(catalog.table.name)
    app.state.query_service = QueryOrchestrator(app.state.datasets, RouterAgent(fake), PlannerAgent(fake), RagIndex(settings.faiss_index_path, FakeEmbeddings()), SQLAgent(fake), settings)
    return client, app, catalog, fake, settings


def test_end_to_end_verified_and_schema_route(tmp_path):
    client, app, catalog, fake, settings = fixture(tmp_path)
    payload = {'dataset_id': catalog.dataset.id, 'question': 'Top 5 regions by revenue'}
    response = client.post('/api/query', json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['query_id'].startswith('q_')
    assert body['status'] == 'verified'
    assert body['validation']['status'] == 'approved'
    assert body['result']['row_count'] == 2
    assert 'SUM(revenue)' in body['sql']
    assert body['plan']['dimensions'] == ['region']
    assert any(d['column_name'] == 'revenue' for d in body['evidence']['documents'])
    assert [s['name'] for s in body['metadata']['stages']] == ['routing', 'planning', 'validation', 'retrieval', 'sql_generation', 'validation', 'execution', 'result_profiling', 'synthesis', 'visualization']
    assert fake.calls == ['RouterResult', 'PlannerResult', 'GeneratedSQL', 'Synthesis']
    manifest = Path(settings.faiss_index_path / catalog.dataset.id / 'manifest.json')
    assert json.loads(manifest.read_text())['schema_hash'] == catalog.dataset.schema_hash
    schema = client.post('/api/query', json={**payload, 'question': 'What columns are available?'})
    assert schema.json()['status'] == 'completed'
    assert schema.json()['sql'] is None
    assert 'region' in schema.json()['answer']


def test_documents_and_faiss_lifecycle(tmp_path):
    _, _, catalog, _, settings = fixture(tmp_path)
    docs = catalog_documents(catalog)
    assert len(docs) == len(catalog.table.columns) + 1
    assert docs == catalog_documents(catalog)
    assert all(d.dataset_id == catalog.dataset.id and d.schema_hash == catalog.dataset.schema_hash for d in docs)
    rag = RagIndex(settings.faiss_index_path, FakeEmbeddings())
    found = rag.retrieve(catalog, 'top regions by revenue', 3)
    assert len(found.documents) == 3
    assert all(d.score <= 1 for d in found.documents)
    original = (settings.faiss_index_path / catalog.dataset.id / 'manifest.json').read_text()
    assert RagIndex(settings.faiss_index_path, FakeEmbeddings()).retrieve(catalog, 'revenue', 2).documents
    assert (settings.faiss_index_path / catalog.dataset.id / 'manifest.json').read_text() == original
    changed = catalog.model_copy(deep=True)
    changed.dataset.version = 'different'
    RagIndex(settings.faiss_index_path, FakeEmbeddings()).retrieve(changed, 'revenue', 2)
    assert json.loads((settings.faiss_index_path / catalog.dataset.id / 'manifest.json').read_text())['dataset_version'] == 'different'
    class OtherModel(FakeEmbeddings):
        model = 'other-model'
    RagIndex(settings.faiss_index_path, OtherModel()).retrieve(catalog, 'revenue', 2)
    assert json.loads((settings.faiss_index_path / catalog.dataset.id / 'manifest.json').read_text())['embedding_model'] == 'other-model'
    class WrongDimension(OtherModel):
        def embed_batch(self, texts):
            return [[1, 1, 1] for _ in texts]
    with pytest.raises(ProviderError, match='invalid_embedding'):
        RagIndex(settings.faiss_index_path, WrongDimension()).retrieve(catalog, 'revenue', 2)


def test_retrieval_evaluation_fixture(tmp_path):
    _, _, catalog, _, settings = fixture(tmp_path)
    cases = json.loads((Path(__file__).parents[2] / 'evaluation' / 'phase2_retrieval.json').read_text())
    rag = RagIndex(settings.faiss_index_path, FakeEmbeddings())
    for case in cases:
        found = rag.retrieve(catalog, case['question'], 4)
        names = {d.column_name for d in found.documents}
        assert set(case['columns']) <= names, (case['question'], names)


def test_grounding_and_request_limits(tmp_path):
    client, _, catalog, _, settings = fixture(tmp_path)
    plan = PlannerResult(objective='bad', tables_needed=[catalog.table.name], dimensions=['invented'], measures=[], filters=[], joins=[], group_by=[], order_by=[], assumptions=[])
    with pytest.raises(PipelineFailure):
        check_plan(plan, catalog)
    valid = PlannerResult(objective='Revenue in 2025', tables_needed=[catalog.table.name], dimensions=['region'], measures=[{'field': 'revenue', 'aggregation': 'SUM'}, {'field': 'order_id', 'aggregation': 'COUNT'}], filters=[{'field': 'order_date', 'operator': 'YEAR_EQ', 'value': 2025}], joins=[], group_by=['region'], order_by=[{'field': 'total_revenue', 'direction': 'DESC'}], limit=5, assumptions=['Dates use calendar year'])
    check_plan(valid, catalog, 5)
    with pytest.raises(PipelineFailure, match='plan_limit_exceeded'):
        check_plan(valid, catalog, 4)
    with pytest.raises(PipelineFailure, match='schema_grounding_failed'):
        check_plan(valid.model_copy(update={'tables_needed': ['secret_table']}), catalog)
    for sql in ('DROP TABLE x', 'SELECT * FROM x', 'SELECT * FROM secret_table'):
        assert SQLGuard().validate(sql, catalog)[0].status == 'rejected'
    assert client.post('/api/query', json={'dataset_id': catalog.dataset.id, 'question': 'Revenue', 'max_rows': settings.max_result_rows + 1}).status_code == 422
    assert client.post('/api/query', json={'dataset_id': 'deadbeef', 'question': 'Revenue'}).status_code == 404
    assert client.post('/api/query', json={'dataset_id': catalog.dataset.id, 'question': '   '}).status_code == 422


def test_router_and_provider_failures(tmp_path, monkeypatch):
    client, app, catalog, fake, _ = fixture(tmp_path)
    assert RouterAgent(fake).run('Drop the sales table', 'q').route == Route.unsupported
    assert client.post('/api/query', json={'dataset_id': catalog.dataset.id, 'question': 'Drop the sales table'}).json()['status'] == 'unsupported'
    provider = OllamaProvider(Settings(llm_model='example', embedding_model='example-embed'))
    monkeypatch.setattr(httpx, 'post', lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ReadTimeout('timeout')))
    with pytest.raises(ProviderError, match='provider_timeout'):
        provider.generate_structured('system', 'user', RouterResult)
    monkeypatch.setattr(httpx, 'post', lambda *args, **kwargs: httpx.Response(200, json={'message': {'content': '{"route":"unknown"}'}}, request=httpx.Request('POST', 'http://localhost:11434')))
    with pytest.raises(ProviderError, match='malformed_provider_output'):
        provider.generate_structured('system', 'user', RouterResult)
    app.state.query_service = None
    assert client.post('/api/query', json={'dataset_id': catalog.dataset.id, 'question': 'Revenue'}).status_code == 503


def test_router_variants_and_schema_validation():
    class FixedLLM:
        def __init__(self, data): self.data = data
        def generate_structured(self, system, user, output): return output.model_validate(self.data)

    for route in ('analytics_query', 'schema_question', 'general_question', 'follow_up', 'unsupported'):
        agent = RouterAgent(FixedLLM({'route': route, 'requires_database': False, 'requires_visualization': False, 'confidence': .8}))
        assert agent.run('Hello', 'q').route.value == route
    with pytest.raises(ValueError):
        RouterAgent(FixedLLM({'route': 'unknown', 'requires_database': False, 'requires_visualization': False, 'confidence': .8})).run('Hello', 'q')
    with pytest.raises(ValueError):
        RouterAgent(FixedLLM({'route': 'analytics_query', 'requires_database': True, 'requires_visualization': False, 'confidence': 1.2})).run('Revenue', 'q')


def test_provider_structured_and_embedding_contract(monkeypatch):
    calls = []
    def response(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith('/api/embed'):
            body = {'embeddings': [[1, 0], [0, 1]]}
        else:
            body = {'message': {'content': json.dumps({'route': 'analytics_query', 'requires_database': True, 'requires_visualization': False, 'confidence': .9})}}
        return httpx.Response(200, json=body, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx, 'post', response)
    provider = OllamaProvider(Settings(llm_model='chat', embedding_model='embed'))
    assert provider.generate_structured('system', 'question', RouterResult).route == Route.analytics_query
    assert provider.embed_batch(['first', 'second']) == [[1, 0], [0, 1]]
    assert calls[0][1]['json']['format']['type'] == 'object'
    assert 'headers' not in calls[0][1]


def test_orchestrator_provider_failure_is_safe(tmp_path):
    client, app, catalog, _, settings = fixture(tmp_path)
    class BrokenLLM:
        def generate_structured(self, system, user, output):
            raise ProviderError('provider_timeout')
    app.state.query_service = QueryOrchestrator(app.state.datasets, RouterAgent(BrokenLLM()), PlannerAgent(BrokenLLM()), RagIndex(settings.faiss_index_path, FakeEmbeddings()), SQLAgent(BrokenLLM()), settings)
    body = client.post('/api/query', json={'dataset_id': catalog.dataset.id, 'question': 'Revenue'}).json()
    assert body['status'] == 'failed'
    assert body['error']['code'] == 'provider_timeout'
    assert body['sql'] is None and body['result'] is None
