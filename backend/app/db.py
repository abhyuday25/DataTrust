from contextlib import contextmanager
from pathlib import Path
from threading import Lock

import duckdb


class Database:
    """Trusted catalog and ingestion writes. Future analytical SQL needs a separate read-only executor."""

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
