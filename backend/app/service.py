import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import duckdb
from fastapi import UploadFile

from app.adapters import reader_for
from app.core import ApiError, Settings
from app.db import Database
from app.schemas import ColumnMetadata, ColumnProfile, DatasetSchema, DatasetSummary, TableMetadata


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def schema_hash(columns: list[tuple[str, str]]) -> str:
    canonical = json.dumps(sorted((name, dtype.upper()) for name, dtype in columns), separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class DatasetService:
    def __init__(self, db: Database, settings: Settings):
        self.db, self.settings = db, settings

    def list(self, user_id: str | None = None, admin: bool = True) -> list[DatasetSummary]:
        with self.db.connection() as con:
            if admin:
                rows = con.execute('SELECT id,name,version,schema_hash,row_count,created_at,updated_at FROM datasets ORDER BY created_at DESC').fetchall()
            else:
                rows = con.execute('''SELECT id,name,version,schema_hash,row_count,created_at,updated_at FROM datasets
                    WHERE owner_id=? OR id IN (SELECT dataset_id FROM dataset_permissions WHERE user_id=?)
                    ORDER BY created_at DESC''', [user_id, user_id]).fetchall()
        return [DatasetSummary.model_validate(dict(zip(DatasetSummary.model_fields, row))) for row in rows]

    def schema(self, dataset_id: str) -> DatasetSchema:
        with self.db.connection() as con:
            row = con.execute('SELECT id,name,version,schema_hash,table_name,row_count,created_at,updated_at,columns_json,warnings_json FROM datasets WHERE id=?', [dataset_id]).fetchone()
        if row is None:
            raise ApiError(404, 'not_found', 'Dataset not found')
        id_, name, version, hash_, table_name, count, created, updated, columns, warnings = row
        return DatasetSchema(dataset=DatasetSummary(id=id_, name=name, version=version, schema_hash=hash_, row_count=count, created_at=created, updated_at=updated), table=TableMetadata(name=table_name, row_count=count, columns=[ColumnMetadata.model_validate(c) for c in json.loads(columns)]), warnings=json.loads(warnings))

    async def upload(self, file: UploadFile, owner_id: str = 'local') -> DatasetSchema:
        original = Path((file.filename or '').replace('\\', '/')).name
        suffix = Path(original).suffix.lower()
        reader_for(Path('upload' + suffix))
        name = Path(original).stem.strip()
        if not name or not re.search(r'\w', name):
            raise ApiError(422, 'invalid_name', 'Filename needs a usable name')
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        dataset_id = uuid4().hex
        table_name = 'dataset_' + dataset_id
        target = self.settings.data_dir / (dataset_id + suffix)
        digest = hashlib.sha256()
        size = 0
        try:
            with target.open('xb') as out:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.settings.max_upload_mb * 1024 * 1024:
                        raise ApiError(413, 'upload_too_large', 'File exceeds upload limit')
                    digest.update(chunk)
                    out.write(chunk)
            if size == 0:
                raise ApiError(422, 'empty_file', 'File is empty')
            with self.db.connection() as con:
                if con.execute('SELECT 1 FROM datasets WHERE lower(name)=lower(?) AND owner_id=?', [name, owner_id]).fetchone():
                    raise ApiError(409, 'duplicate_name', 'A dataset with this name already exists')
                try:
                    con.execute('BEGIN TRANSACTION')
                    # Reader name is from the fixed allow-list; file path is parameterized.
                    con.execute(f'CREATE TABLE {quote(table_name)} AS SELECT * FROM {reader_for(target)}(?)', [str(target)])
                    details = con.execute(f'DESCRIBE {quote(table_name)}').fetchall()
                    columns = [(r[0], r[1]) for r in details]
                    if not columns or len({n.casefold() for n, _ in columns}) != len(columns):
                        raise ApiError(422, 'invalid_structure', 'Dataset needs unique usable columns')
                    count = con.execute(f'SELECT COUNT(*) FROM {quote(table_name)}').fetchone()[0]
                    metadata, warnings = self._profile(con, table_name, columns, count)
                    now = datetime.now(timezone.utc)
                    con.execute('INSERT INTO datasets (id,name,version,schema_hash,table_name,row_count,created_at,updated_at,columns_json,warnings_json,owner_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)', [dataset_id, name, digest.hexdigest(), schema_hash(columns), table_name, count, now, now, json.dumps(metadata, default=str), json.dumps(warnings), owner_id])
                    con.execute('COMMIT')
                except Exception:
                    con.execute('ROLLBACK')
                    raise
            return self.schema(dataset_id)
        except ApiError:
            target.unlink(missing_ok=True)
            raise
        except (duckdb.Error, ValueError, OSError):
            target.unlink(missing_ok=True)
            raise ApiError(422, 'invalid_dataset', 'File could not be read as a dataset') from None

    def _profile(self, con: duckdb.DuckDBPyConnection, table: str, columns: list[tuple[str, str]], count: int):
        metadata = []
        warnings = []
        sample_size = min(count, 10000)
        if count > sample_size:
            warnings.append('Column statistics use the first 10000 rows; row count covers all rows')
        for name, dtype in columns:
            q = quote(name)
            try:
                # Sampling bounds distinct and range work for large uploads.
                source = f'(SELECT {q} FROM {quote(table)} LIMIT 10000)'
                nulls, distinct, low, high = con.execute(f'SELECT COUNT(*) FILTER (WHERE {q} IS NULL), COUNT(DISTINCT {q}), MIN({q}), MAX({q}) FROM {source}').fetchone()
                samples = [r[0] for r in con.execute(f'SELECT DISTINCT {q} FROM {source} WHERE {q} IS NOT NULL LIMIT 5').fetchall()]
                profile = ColumnProfile(null_count=nulls, null_percentage=round(100 * nulls / sample_size, 2) if sample_size else 0, distinct_count=distinct, minimum=str(low) if low is not None else None, maximum=str(high) if high is not None else None, samples=[str(x) for x in samples])
                metadata.append(ColumnMetadata(name=name, dtype=dtype, profile=profile).model_dump())
            except duckdb.Error:
                warnings.append(f'Profiling unavailable for column {name}')
                metadata.append(ColumnMetadata(name=name, dtype=dtype).model_dump())
        return metadata, warnings
