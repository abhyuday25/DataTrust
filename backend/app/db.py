from contextlib import contextmanager
from pathlib import Path
from threading import Lock

import duckdb


class Database:
    """Trusted metadata and ingestion writes; analytical SQL uses ReadOnlyExecutor."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = Lock()

    @contextmanager
    def connection(self):
        with self.lock:
            con = duckdb.connect(str(self.path))
            try:
                yield con
            finally:
                con.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS datasets (
                id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, version VARCHAR NOT NULL,
                schema_hash VARCHAR NOT NULL, table_name VARCHAR NOT NULL,
                row_count BIGINT NOT NULL, created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL, columns_json VARCHAR NOT NULL,
                warnings_json VARCHAR NOT NULL
            )''')
            if 'owner_id' not in {row[0] for row in con.execute('DESCRIBE datasets').fetchall()}:
                con.execute('ALTER TABLE datasets ADD COLUMN owner_id VARCHAR')
            con.execute('''CREATE TABLE IF NOT EXISTS users (
                id VARCHAR PRIMARY KEY, email VARCHAR UNIQUE NOT NULL, role VARCHAR NOT NULL,
                password_hash VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL)''')
            con.execute('''CREATE TABLE IF NOT EXISTS sessions (
                token_hash VARCHAR PRIMARY KEY, user_id VARCHAR NOT NULL, expires_at TIMESTAMP NOT NULL)''')
            con.execute('''CREATE TABLE IF NOT EXISTS dataset_permissions (
                dataset_id VARCHAR NOT NULL, user_id VARCHAR NOT NULL, PRIMARY KEY(dataset_id,user_id))''')
            con.execute('''CREATE TABLE IF NOT EXISTS query_records (
                id VARCHAR PRIMARY KEY, user_id VARCHAR NOT NULL, dataset_id VARCHAR NOT NULL,
                question VARCHAR NOT NULL, status VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL,
                response_json VARCHAR NOT NULL)''')
            con.execute('''CREATE TABLE IF NOT EXISTS feedback (
                query_id VARCHAR NOT NULL, user_id VARCHAR NOT NULL, label VARCHAR NOT NULL,
                comment VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL)''')
            con.execute('''CREATE TABLE IF NOT EXISTS conversations (
                id VARCHAR PRIMARY KEY, user_id VARCHAR NOT NULL, dataset_id VARCHAR NOT NULL,
                dataset_version VARCHAR NOT NULL, schema_hash VARCHAR NOT NULL,
                state_json VARCHAR NOT NULL, updated_at TIMESTAMP NOT NULL)''')
            con.execute('''CREATE TABLE IF NOT EXISTS cache_entries (
                id VARCHAR PRIMARY KEY, user_id VARCHAR NOT NULL, dataset_id VARCHAR NOT NULL,
                dataset_version VARCHAR NOT NULL, schema_hash VARCHAR NOT NULL,
                question VARCHAR NOT NULL, embedding_model VARCHAR NOT NULL,
                embedding_json VARCHAR NOT NULL, max_rows INTEGER NOT NULL, visualize BOOLEAN NOT NULL,
                response_json VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL, expires_at TIMESTAMP NOT NULL)''')
