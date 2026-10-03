"""Small provider boundaries; agent code knows only these protocols."""

import math
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core import Settings

T = TypeVar('T', bound=BaseModel)


class ProviderError(Exception):
    def __init__(self, code: str):
        self.code = code


class LLMClient(Protocol):
    def generate_structured(self, system: str, user: str, output: type[T]) -> T: ...


class EmbeddingProvider(Protocol):
    model: str
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatible:
    def __init__(self, settings: Settings):
        if settings.llm_provider not in ('openai', 'openai_compatible') or not settings.llm_model or not settings.embedding_model or not settings.llm_api_key:
            raise ProviderError('provider_unavailable')
        self.model = settings.embedding_model
        self.chat_model = settings.llm_model
        self.base_url = settings.llm_base_url.rstrip('/')
        self.api_key = settings.llm_api_key
        self.timeout = settings.llm_timeout_seconds

    def _post(self, path: str, payload: dict) -> dict:
        try:
            response = httpx.post(self.base_url + path, json=payload, headers={'Authorization': f'Bearer {self.api_key}'}, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException:
            raise ProviderError('provider_timeout') from None
        except (httpx.HTTPError, ValueError):
            raise ProviderError('provider_failure') from None

    def generate_structured(self, system: str, user: str, output: type[T]) -> T:
        data = self._post('/chat/completions', {
            'model': self.chat_model,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
            'response_format': {'type': 'json_schema', 'json_schema': {'name': output.__name__, 'schema': output.model_json_schema(), 'strict': False}},
        })
        try:
            return output.model_validate_json(data['choices'][0]['message']['content'])
        except (KeyError, IndexError, TypeError, ValidationError, ValueError):
            raise ProviderError('malformed_provider_output') from None

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        data = self._post('/embeddings', {'model': self.model, 'input': texts})
        try:
            ordered = sorted(data['data'], key=lambda item: item['index'])
            if [item['index'] for item in ordered] != list(range(len(texts))):
                raise ValueError
            vectors = [[float(x) for x in item['embedding']] for item in ordered]
            if len(vectors) != len(texts) or not vectors[0] or any(len(v) != len(vectors[0]) or not all(math.isfinite(x) for x in v) for v in vectors):
                raise ValueError
            return vectors
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError('invalid_embedding') from None
