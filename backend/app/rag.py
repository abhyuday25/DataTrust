"""Catalog-derived documents and a per-dataset, version-checked FAISS index."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import faiss
import numpy as np

from app.providers import EmbeddingProvider, ProviderError
from app.query_models import MetadataDocument, RetrievedDocument, RetrievalResult
from app.schemas import DatasetSchema


def catalog_documents(catalog: DatasetSchema) -> list[MetadataDocument]:
    dataset, table = catalog.dataset, catalog.table

    def doc(kind: str, column: str | None, content: str) -> MetadataDocument:
        identity = '|'.join([dataset.id, dataset.version, dataset.schema_hash, kind, table.name, column or ''])
        return MetadataDocument(document_id=hashlib.sha256(identity.encode()).hexdigest()[:24], dataset_id=dataset.id, dataset_version=dataset.version, schema_hash=dataset.schema_hash, object_type=kind, table_name=table.name, column_name=column, content=content)

    table_text = f'Dataset {dataset.name}; table {table.name}; rows {table.row_count}; columns: ' + ', '.join(f'{c.name} {c.dtype}' for c in table.columns)
    if table.description:
        table_text += f'; description: {table.description[:500]}'
    documents = [doc('table', None, table_text[:2000])]
    for column in table.columns:
        parts = [f'Dataset {dataset.name}; table {table.name}; column {column.name}; type {column.dtype}']
        if column.description:
            parts.append(f'description {column.description[:500]}')
        if column.profile:
            p = column.profile
            parts.append(f'nulls {p.null_count} ({p.null_percentage}%); distinct {p.distinct_count}; range {p.minimum} to {p.maximum}')
            if p.samples:
                parts.append('samples ' + ', '.join(str(x)[:64] for x in p.samples[:3]))
        documents.append(doc('column', column.name, '; '.join(parts)[:1000]))
    return documents


class RagIndex:
    def __init__(self, root: Path, embeddings: EmbeddingProvider):
        self.root, self.embeddings = root, embeddings
        # ponytail: one process-wide lock serializes rebuilds; use per-dataset locks if indexing throughput matters.
        self.lock = Lock()

    def _paths(self, dataset_id: str):
        folder = self.root / dataset_id
        return folder, folder / 'index.faiss', folder / 'documents.json', folder / 'manifest.json'

    def _load_or_build(self, catalog: DatasetSchema):
        folder, index_path, docs_path, manifest_path = self._paths(catalog.dataset.id)
        identity = {'dataset_id': catalog.dataset.id, 'dataset_version': catalog.dataset.version, 'schema_hash': catalog.dataset.schema_hash, 'embedding_model': self.embeddings.model}
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if all(manifest.get(key) == value for key, value in identity.items()):
                index = faiss.read_index(str(index_path))
                docs = [MetadataDocument.model_validate(x) for x in json.loads(docs_path.read_text(encoding='utf-8'))]
                if index.ntotal == len(docs) == manifest['document_count'] and index.d == manifest['embedding_dimension'] and all(d.dataset_id == catalog.dataset.id and d.dataset_version == catalog.dataset.version and d.schema_hash == catalog.dataset.schema_hash for d in docs):
                    return index, docs
        except (OSError, ValueError, KeyError, RuntimeError):
            pass
        docs = catalog_documents(catalog)
        vectors = []
        for start in range(0, len(docs), 32):
            vectors.extend(self.embeddings.embed_batch([d.content for d in docs[start:start + 32]]))
        if len(vectors) != len(docs) or not vectors or not vectors[0] or any(len(v) != len(vectors[0]) for v in vectors):
            raise ProviderError('invalid_embedding')
        matrix = np.asarray(vectors, dtype='float32')
        if not np.isfinite(matrix).all() or np.any(np.linalg.norm(matrix, axis=1) == 0):
            raise ProviderError('invalid_embedding')
        faiss.normalize_L2(matrix)
        index = faiss.IndexFlatIP(matrix.shape[1])
        index.add(matrix)
        folder.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(index_path.with_suffix('.tmp')))
        docs_path.with_suffix('.tmp').write_text(json.dumps([d.model_dump() for d in docs]), encoding='utf-8')
        manifest = {**identity, 'embedding_dimension': matrix.shape[1], 'document_count': len(docs), 'created_at': datetime.now(timezone.utc).isoformat()}
        manifest_path.with_suffix('.tmp').write_text(json.dumps(manifest), encoding='utf-8')
        index_path.with_suffix('.tmp').replace(index_path)
        docs_path.with_suffix('.tmp').replace(docs_path)
        manifest_path.with_suffix('.tmp').replace(manifest_path)
        return index, docs

    def retrieve(self, catalog: DatasetSchema, question: str, top_k: int) -> RetrievalResult:
        with self.lock:
            index, docs = self._load_or_build(catalog)
            vector = np.asarray(self.embeddings.embed_batch([question.strip()])[0], dtype='float32').reshape(1, -1)
            if vector.shape[1] != index.d or not np.isfinite(vector).all() or np.linalg.norm(vector) == 0:
                raise ProviderError('invalid_embedding')
            faiss.normalize_L2(vector)
            scores, positions = index.search(vector, min(top_k, index.ntotal))
        found = [RetrievedDocument(document_id=docs[int(pos)].document_id, object_type=docs[int(pos)].object_type, table_name=docs[int(pos)].table_name, column_name=docs[int(pos)].column_name, score=round(float(score), 4), content=docs[int(pos)].content) for score, pos in zip(scores[0], positions[0]) if pos >= 0]
        return RetrievalResult(dataset_id=catalog.dataset.id, documents=found)


def context_for(result: RetrievalResult) -> str:
    return '\n'.join(f'[{d.document_id}] {d.content[:1000]}' for d in result.documents)[:12000]
