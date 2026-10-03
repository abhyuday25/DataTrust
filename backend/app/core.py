import json
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    app_env: str = 'development'
    duckdb_path: Path = Path('./storage/datatrust.duckdb')
    data_dir: Path = Path('./data/uploads')
    max_upload_mb: int = Field(default=100, gt=0)
    cors_origins: str = 'http://localhost:5173'
    llm_provider: str = 'ollama'
    llm_model: str = ''
    ollama_base_url: str = 'http://localhost:11434'
    llm_timeout_seconds: int = Field(default=30, gt=0)
    embedding_model: str = ''
    rag_top_k: int = Field(default=5, ge=1, le=20)
    faiss_index_path: Path = Path('./storage/faiss')
    max_result_rows: int = Field(default=10000, ge=1)
    query_timeout_seconds: int = Field(default=10, ge=1)
    max_repair_attempts: int = Field(default=2, ge=0, le=2)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def create_app(settings: Settings | None = None) -> FastAPI:
    from app.db import Database
    from app.routes import router
    from app.service import DatasetService
    from app.providers import OllamaProvider, ProviderError
    from app.agents import RouterAgent, PlannerAgent, SQLAgent
    from app.rag import RagIndex
    from app.query_service import QueryOrchestrator

    settings = settings or Settings()
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    db = Database(settings.duckdb_path)
    db.initialize()
    app = FastAPI(title='DataTrust', version='0.2.0')
    app.state.settings = settings
    app.state.datasets = DatasetService(db, settings)
    app.state.query_service = None
    try:
        provider = OllamaProvider(settings)
        app.state.query_service = QueryOrchestrator(app.state.datasets, RouterAgent(provider), PlannerAgent(provider), RagIndex(settings.faiss_index_path, provider), SQLAgent(provider), settings)
    except ProviderError:
        pass  # Dataset management remains available without AI credentials.
    app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(',') if x.strip()], allow_methods=['GET', 'POST'], allow_headers=['*'])

    @app.middleware('http')
    async def request_context(request: Request, call_next):
        request_id = str(uuid4())
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            logging.error(json.dumps({'event': 'request_failed', 'request_id': request_id}))
            response = JSONResponse(status_code=500, content={'error': {'code': 'internal_error', 'message': 'Internal server error', 'request_id': request_id}})
        response.headers['X-Request-ID'] = request_id
        logging.info(json.dumps({'event': 'request', 'request_id': request_id, 'method': request.method, 'path': request.url.path, 'status': response.status_code}))
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status, content={'error': {'code': exc.code, 'message': exc.message}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={'error': {'code': 'validation_error', 'message': 'Invalid request'}})

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={'error': {'code': 'http_error', 'message': str(exc.detail)}})

    app.include_router(router, prefix='/api')
    return app
