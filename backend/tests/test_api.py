import hashlib

import duckdb
from fastapi.testclient import TestClient

from app.core import Settings, create_app
from app.service import schema_hash


def client(tmp_path, max_mb=1):
    return TestClient(create_app(Settings(duckdb_path=tmp_path / 'catalog.duckdb', data_dir=tmp_path / 'uploads', max_upload_mb=max_mb)))


def test_csv_upload_catalog_restart_and_version(tmp_path):
    csv = b'order_id,region,revenue\n1,North,12.5\n2,South,\n'
    with client(tmp_path) as api:
        assert api.get('/api/health').json() == {'status': 'ok'}
        response = api.post('/api/datasets/upload', files={'file': ('sales.csv', csv)})
        assert response.status_code == 201, response.text
        body = response.json()
        dataset = body['dataset']
        assert dataset['version'] == hashlib.sha256(csv).hexdigest()
        assert dataset['schema_hash'] == schema_hash([('order_id', 'BIGINT'), ('region', 'VARCHAR'), ('revenue', 'DOUBLE')])
        assert body['table']['row_count'] == 2
        assert body['table']['columns'][2]['profile']['null_count'] == 1
        assert api.get('/api/datasets').json()[0]['id'] == dataset['id']
        assert api.get(f"/api/datasets/{dataset['id']}/schema").json() == body
        assert api.post('/api/datasets/upload', files={'file': ('sales.csv', csv)}).status_code == 409
    with client(tmp_path) as api:
        assert api.get(f"/api/datasets/{dataset['id']}/schema").json() == body


def test_parquet_upload(tmp_path):
    parquet = tmp_path / 'source.parquet'
    con = duckdb.connect()
    con.execute("COPY (SELECT 1 AS quantity, 'East' AS region) TO ? (FORMAT PARQUET)", [str(parquet)])
    con.close()
    with client(tmp_path) as api:
        response = api.post('/api/datasets/upload', files={'file': ('sample.parquet', parquet.read_bytes())})
        assert response.status_code == 201, response.text
        assert response.json()['table']['row_count'] == 1


def test_upload_validation_and_sanitized_errors(tmp_path):
    with client(tmp_path) as api:
        assert api.post('/api/datasets/upload', files={'file': ('bad.exe', b'x')}).status_code == 415
        assert api.post('/api/datasets/upload', files={'file': ('empty.csv', b'')}).status_code == 422
        malformed = api.post('/api/datasets/upload', files={'file': ('bad.parquet', b'not parquet')})
        assert malformed.status_code == 422
        assert str(tmp_path) not in malformed.text
        assert 'duckdb' not in malformed.text.lower()
        unsafe = api.post('/api/datasets/upload', files={'file': ('../../escape.csv', b'a\n1\n')})
        assert unsafe.status_code == 201
        assert not (tmp_path / 'escape.csv').exists()
        assert list((tmp_path / 'uploads').glob('*.csv'))[0].stem == unsafe.json()['dataset']['id']
        assert api.get('/api/datasets/absent/schema').status_code == 404
        assert api.post('/api/query', json={'sql': 'DROP TABLE datasets'}).status_code == 422


def test_size_limit(tmp_path):
    with client(tmp_path) as api:
        response = api.post('/api/datasets/upload', files={'file': ('big.csv', b'a\n' + b'1' * (1024 * 1024))})
        assert response.status_code == 413
        assert list((tmp_path / 'uploads').iterdir()) == []


def test_schema_hash_ignores_order(tmp_path):
    assert schema_hash([('b', 'INTEGER'), ('a', 'VARCHAR')]) == schema_hash([('a', 'VARCHAR'), ('b', 'INTEGER')])
