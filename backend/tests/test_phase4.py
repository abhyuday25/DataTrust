import json
import io

import pytest
from openpyxl import load_workbook

from fastapi.testclient import TestClient

from app.agents import PlannerAgent, RouterAgent, SQLAgent
from app.core import Settings, create_app
from app.query_service import QueryOrchestrator
from app.query_models import Filter, GeneratedSQL, PlannerResult, RouterResult, Route
from app.rag import RagIndex
from test_phase2 import FakeEmbeddings, FakeLLM


CSV = b'order_id,region,revenue,order_date\n1,North,12.5,2025-01-01\n2,South,7.0,2025-02-01\n'


def wired_app(tmp_path, auth=False):
    settings = Settings(duckdb_path=tmp_path / 'data.duckdb', data_dir=tmp_path / 'uploads',
        faiss_index_path=tmp_path / 'faiss', auth_enabled=auth,
        admin_email='admin@example.com' if auth else '', admin_password='a-long-admin-password' if auth else '')
    app = create_app(settings)
    client = TestClient(app)
    return client, app, settings


def fake_pipeline(app, settings, table):
    llm = FakeLLM(table)
    app.state.query_service = QueryOrchestrator(app.state.datasets, RouterAgent(llm), PlannerAgent(llm),
        RagIndex(settings.faiss_index_path, FakeEmbeddings()), SQLAgent(llm), settings,
        app.state.store, app.state.metrics)
    return llm


def test_cache_history_conversation_and_export(tmp_path, monkeypatch):
    client, app, settings = wired_app(tmp_path)
    uploaded = client.post('/api/datasets/upload', files={'file': ('sales.csv', CSV)}).json()
    dataset_id, table = uploaded['dataset']['id'], uploaded['table']['name']
    llm = fake_pipeline(app, settings, table)
    payload = {'dataset_id': dataset_id, 'question': 'Top 5 regions by revenue', 'visualize': True}
    first = client.post('/api/query', json=payload).json()
    assert first['status'] == 'verified' and first['conversation_id']
    monkeypatch.setattr(app.state.query_service.executor, 'execute', lambda *args: (_ for _ in ()).throw(AssertionError('cache must not reexecute SQL')))
    second = client.post('/api/query', json=payload).json()
    assert second['status'] == 'verified' and second['metadata']['cache_hit']
    assert second['query_id'] != first['query_id']
    assert llm.calls.count('GeneratedSQL') == 1
    assert len(client.get('/api/history').json()) == 2
    detail = client.get('/api/query/' + first['query_id']).json()
    assert detail['response']['sql'] == first['sql']
    assert client.post('/api/query/' + first['query_id'] + '/feedback', json={'label': 'correct'}).status_code == 200
    csv_file = client.get('/api/query/' + first['query_id'] + '/export?format=csv')
    assert csv_file.status_code == 200 and b'North,12.5' in csv_file.content
    xlsx_file = client.get('/api/query/' + first['query_id'] + '/export?format=xlsx')
    assert xlsx_file.status_code == 200 and xlsx_file.content.startswith(b'PK')
    valid = client.post('/api/query/validate', json={'dataset_id': dataset_id, 'sql': first['sql']}).json()
    assert valid['status'] == 'approved'
    assert client.post('/api/query/validate', json={'dataset_id': dataset_id, 'sql': 'DROP TABLE datasets'}).json()['status'] == 'rejected'
    assert client.get('/api/metrics').json()['counts']['cache_hits'] == 1
    restarted = create_app(settings)
    fake_pipeline(restarted, settings, table)
    persisted = TestClient(restarted).post('/api/query', json=payload).json()
    assert persisted['metadata']['cache_hit'] is True


def test_export_escapes_spreadsheet_formulas(tmp_path):
    client, app, settings = wired_app(tmp_path)
    uploaded = client.post('/api/datasets/upload', files={'file': ('sales.csv', CSV)}).json()
    fake_pipeline(app, settings, uploaded['table']['name'])
    response = client.post('/api/query', json={'dataset_id': uploaded['dataset']['id'], 'question': 'Top regions'}).json()
    assert response['status'] == 'verified'
    response['result']['columns'][0] = '=danger()'
    response['result']['rows'][0][0] = ' =danger()'
    with app.state.datasets.db.connection() as con:
        con.execute('UPDATE query_records SET response_json=? WHERE id=?', [json.dumps(response), response['query_id']])
    csv_body = client.get('/api/query/' + response['query_id'] + '/export').content.decode('utf-8-sig')
    assert "'=danger()" in csv_body and "' =danger()" in csv_body
    xlsx_body = client.get('/api/query/' + response['query_id'] + '/export?format=xlsx').content
    sheet = load_workbook(io.BytesIO(xlsx_body), read_only=True).active
    assert sheet['A1'].value == "'=danger()"
    assert sheet['A2'].value == "' =danger()"


def test_production_requires_auth(tmp_path):
    with pytest.raises(ValueError, match='AUTH_ENABLED'):
        create_app(Settings(app_env='production', duckdb_path=tmp_path / 'data.duckdb', auth_enabled=False))


def test_cache_identity_expiry_and_similarity(tmp_path):
    client, app, settings = wired_app(tmp_path)
    uploaded = client.post('/api/datasets/upload', files={'file': ('sales.csv', CSV)}).json()
    catalog = app.state.datasets.schema(uploaded['dataset']['id'])
    fake_pipeline(app, settings, catalog.table.name)
    question = 'Top 5 regions by revenue'
    assert client.post('/api/query', json={'dataset_id': catalog.dataset.id, 'question': question}).json()['status'] == 'verified'
    vector = FakeEmbeddings().embed_batch([question])[0]
    store = app.state.store
    def find(catalog_arg=catalog, vector_arg=vector):
        return store.cache_find('local', catalog_arg, vector_arg, 'fake-4d', 1000, False)[0]
    assert find() is not None
    assert find(vector_arg=[0, 0, 0, 1]) is None
    changed = catalog.model_copy(deep=True)
    changed.dataset.version = 'different'
    assert find(catalog_arg=changed) is None
    changed = catalog.model_copy(deep=True)
    changed.dataset.schema_hash = 'different'
    assert find(catalog_arg=changed) is None
    with app.state.datasets.db.connection() as con:
        con.execute("UPDATE cache_entries SET expires_at=TIMESTAMP '2000-01-01'")
    assert find() is None


def test_auth_permissions_and_history_isolation(tmp_path):
    client, app, settings = wired_app(tmp_path, auth=True)
    assert client.get('/api/datasets').status_code == 401
    assert client.post('/api/auth/login', json={'email': 'admin@example.com', 'password': 'wrong'}).status_code == 401
    token = client.post('/api/auth/login', json={'email': 'admin@example.com', 'password': 'a-long-admin-password'}).json()['access_token']
    admin = {'Authorization': 'Bearer ' + token}
    u1 = client.post('/api/auth/users', headers=admin, json={'email': 'one@example.com', 'password': 'long-password-one'}).json()['id']
    client.post('/api/auth/users', headers=admin, json={'email': 'two@example.com', 'password': 'long-password-two'})
    def login(email, password):
        return {'Authorization': 'Bearer ' + client.post('/api/auth/login', json={'email': email, 'password': password}).json()['access_token']}
    one, two = login('one@example.com', 'long-password-one'), login('two@example.com', 'long-password-two')
    uploaded = client.post('/api/datasets/upload', headers=admin, files={'file': ('sales.csv', CSV)}).json()
    dataset_id = uploaded['dataset']['id']
    assert client.get('/api/datasets', headers=one).json() == []
    assert client.get('/api/datasets/' + dataset_id + '/schema', headers=one).status_code == 404
    assert client.post('/api/query/validate', headers=one, json={'dataset_id': dataset_id, 'sql': 'SELECT 1'}).status_code == 404
    assert client.post('/api/datasets/' + dataset_id + '/permissions', headers=admin, json={'user_id': u1}).status_code == 200
    assert len(client.get('/api/datasets', headers=one).json()) == 1
    llm = fake_pipeline(app, settings, uploaded['table']['name'])
    body = client.post('/api/query', headers=one, json={'dataset_id': dataset_id, 'question': 'Top regions by revenue'}).json()
    assert body['status'] == 'verified'
    assert client.get('/api/history', headers=one).json()[0]['query_id'] == body['query_id']
    assert client.get('/api/history', headers=two).json() == []
    assert client.get('/api/query/' + body['query_id'], headers=two).status_code == 404
    assert client.get('/api/query/' + body['query_id'] + '/export', headers=two).status_code == 404
    assert client.post('/api/query/' + body['query_id'] + '/feedback', headers=two, json={'label': 'incorrect'}).status_code == 404
    assert client.get('/api/metrics', headers=one).status_code == 403
    assert client.get('/api/metrics', headers=admin).status_code == 200
    assert client.post('/api/datasets/' + dataset_id + '/permissions', headers=admin, json={'user_id': client.post('/api/auth/users', headers=admin, json={'email': 'three@example.com', 'password': 'long-password-three'}).json()['id']}).status_code == 200
    three = login('three@example.com', 'long-password-three')
    assert client.post('/api/query', headers=three, json={'dataset_id': dataset_id, 'question': 'Top regions by revenue', 'conversation_id': body['conversation_id']}).status_code == 404
    own = client.post('/api/query', headers=three, json={'dataset_id': dataset_id, 'question': 'Top regions by revenue'}).json()
    assert own['status'] == 'verified' and not own['metadata']['cache_hit']
    assert llm.calls.count('GeneratedSQL') == 2
    assert client.post('/api/auth/logout', headers=two).status_code == 200
    assert client.get('/api/datasets', headers=two).status_code == 401


class FollowupLLM(FakeLLM):
    def generate_structured(self, system, user, output):
        if output is RouterResult:
            follow = user.lower().startswith(('now ', 'break ', 'make '))
            return RouterResult(route=Route.follow_up if follow else Route.analytics_query,
                requires_database=True, requires_visualization=True, confidence=1)
        if output is PlannerResult:
            data = json.loads(user) if user.startswith('{') else None
            if data and 'previous_plan' in data:
                plan = PlannerResult.model_validate(data['previous_plan'])
                question = data['follow_up'].lower()
                if 'south' in question:
                    plan.filters.append(Filter(field='region', operator='EQ', value='South'))
                if 'month' in question:
                    plan.dimensions = ['order_date']; plan.group_by = ['order_date']
                if 'line' in question:
                    plan.visualization = 'line'
                return plan
            return PlannerResult(objective='Revenue in 2025', tables_needed=[self.table], dimensions=['region'],
                measures=[{'field': 'revenue', 'aggregation': 'SUM'}], filters=[{'field': 'order_date', 'operator': 'YEAR_EQ', 'value': 2025}],
                joins=[], group_by=['region'], order_by=[], limit=5, assumptions=[])
        if output is GeneratedSQL:
            plan = PlannerResult.model_validate(json.loads(user)['plan'])
            month = plan.dimensions == ['order_date']
            south = any(item.field == 'region' and item.value == 'South' for item in plan.filters)
            dimension = "STRFTIME(order_date, '%Y-%m') AS month" if month else 'region'
            sql = f'SELECT {dimension}, SUM(revenue) AS total_revenue FROM "{self.table}" WHERE EXTRACT(YEAR FROM order_date)=2025'
            if south: sql += " AND region='South'"
            sql += ' GROUP BY month ORDER BY month' if month else ' GROUP BY region'
            return GeneratedSQL(sql=sql, referenced_tables=[self.table], referenced_columns=[], assumptions=[])
        return super().generate_structured(system, user, output)


def test_structured_followups_and_dataset_boundary(tmp_path):
    client, app, settings = wired_app(tmp_path)
    uploaded = client.post('/api/datasets/upload', files={'file': ('sales.csv', CSV)}).json()
    dataset_id = uploaded['dataset']['id']
    llm = FollowupLLM(uploaded['table']['name'])
    app.state.query_service = QueryOrchestrator(app.state.datasets, RouterAgent(llm), PlannerAgent(llm),
        RagIndex(settings.faiss_index_path, FakeEmbeddings()), SQLAgent(llm), settings,
        app.state.store, app.state.metrics)
    first = client.post('/api/query', json={'dataset_id': dataset_id, 'question': 'Revenue by region in 2025', 'visualize': True}).json()
    assert first['status'] == 'verified'
    conv = first['conversation_id']
    for question, expected in [('Now only South', 'South'), ('Break that down by month', 'month'), ('Make it a line chart', 'line')]:
        body = client.post('/api/query', json={'dataset_id': dataset_id, 'question': question, 'conversation_id': conv, 'visualize': True}).json()
        assert body['status'] == 'verified', body
        assert body['conversation_id'] == conv
        if expected == 'South': assert body['result']['rows'] == [['South', 7.0]]
        if expected == 'month': assert body['result']['columns'][0] == 'month'
        if expected == 'line': assert body['visualization']['type'] == 'line'
    other = client.post('/api/datasets/upload', files={'file': ('other.csv', CSV)}).json()['dataset']['id']
    assert client.post('/api/query', json={'dataset_id': other, 'question': 'Now only South', 'conversation_id': conv}).status_code == 409
    with app.state.datasets.db.connection() as con:
        con.execute("UPDATE conversations SET schema_hash='stale' WHERE id=?", [conv])
    assert client.post('/api/query', json={'dataset_id': dataset_id, 'question': 'Now only South', 'conversation_id': conv}).status_code == 409
