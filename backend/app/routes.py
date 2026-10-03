import csv
import io
import re

from fastapi import APIRouter, Depends, File, Header, Query, Request, UploadFile
from fastapi.responses import Response
import httpx
from openpyxl import Workbook
from pydantic import BaseModel, Field

from app.schemas import DatasetSchema, DatasetSummary
from app.service import DatasetService
from app.core import ApiError
from app.query_models import QueryRequest, QueryResponse
from app.auth import Principal
from app.sql_guard import SQLGuard, ValidationResult


router = APIRouter()


def service(request: Request) -> DatasetService:
    return request.app.state.datasets


def principal(request: Request, authorization: str | None = Header(default=None)) -> Principal:
    return request.app.state.auth.current(authorization)


class LoginRequest(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=12)
    role: str = 'user'


class GrantRequest(BaseModel):
    user_id: str


class ValidationRequest(BaseModel):
    dataset_id: str = Field(pattern=r'^[a-f0-9]+$')
    sql: str = Field(min_length=1, max_length=100000)


class FeedbackRequest(BaseModel):
    label: str = Field(pattern=r'^(correct|incorrect|partially_correct)$')
    comment: str = Field(default='', max_length=2000)


@router.post('/auth/login')
def login(payload: LoginRequest, request: Request):
    return {'access_token': request.app.state.auth.login(payload.email, payload.password), 'token_type': 'bearer'}


@router.post('/auth/logout')
def logout(request: Request, authorization: str | None = Header(default=None), user: Principal = Depends(principal)):
    request.app.state.auth.logout(authorization)
    return {'status': 'signed_out'}


@router.post('/auth/users', status_code=201)
def create_user(payload: UserCreate, request: Request, user: Principal = Depends(principal)):
    request.app.state.auth.require_admin(user)
    return {'id': request.app.state.auth.create_user(payload.email, payload.password, payload.role)}


@router.post('/datasets/{dataset_id}/permissions')
def grant_dataset(dataset_id: str, payload: GrantRequest, request: Request, user: Principal = Depends(principal)):
    request.app.state.auth.require_admin(user)
    request.app.state.auth.grant(dataset_id, payload.user_id)
    return {'status': 'granted'}


@router.get('/health')
def health():
    return {'status': 'ok'}


@router.get('/readiness')
def readiness(request: Request):
    settings = request.app.state.settings
    if request.app.state.query_service is None:
        return {'status': 'unavailable', 'provider': 'ollama'}
    try:
        response = httpx.get(settings.ollama_base_url.rstrip('/') + '/api/tags', timeout=2)
        response.raise_for_status()
        models = {item['name'] for item in response.json().get('models', [])}
        ready = all(model in models or model + ':latest' in models for model in (settings.llm_model, settings.embedding_model))
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        ready = False
    return {'status': 'ready' if ready else 'unavailable', 'provider': 'ollama'}


@router.post('/datasets/upload', response_model=DatasetSchema, status_code=201)
async def upload(file: UploadFile = File(...), datasets: DatasetService = Depends(service), user: Principal = Depends(principal)):
    return await datasets.upload(file, user.id)


@router.get('/datasets', response_model=list[DatasetSummary])
def list_datasets(datasets: DatasetService = Depends(service), user: Principal = Depends(principal)):
    return datasets.list(user.id, user.role == 'admin')


@router.get('/datasets/{dataset_id}/schema', response_model=DatasetSchema)
def dataset_schema(dataset_id: str, request: Request, datasets: DatasetService = Depends(service), user: Principal = Depends(principal)):
    request.app.state.auth.require_dataset(user, dataset_id)
    return datasets.schema(dataset_id)


@router.post('/query/validate', response_model=ValidationResult)
def validate_query(payload: ValidationRequest, request: Request, user: Principal = Depends(principal)):
    request.app.state.auth.require_dataset(user, payload.dataset_id)
    catalog = request.app.state.datasets.schema(payload.dataset_id)
    return SQLGuard().validate(payload.sql, catalog)[0]


@router.post('/query', response_model=QueryResponse)
def query(payload: QueryRequest, request: Request, user: Principal = Depends(principal)):
    request.app.state.auth.require_dataset(user, payload.dataset_id)
    if request.app.state.query_service is None:
        raise ApiError(503, 'provider_unavailable', 'Configure local Ollama models to use queries')
    return request.app.state.query_service.run(payload, request.state.request_id, user.id)


@router.get('/history')
def history(request: Request, limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
            dataset_id: str | None = None, status: str | None = None, user: Principal = Depends(principal)):
    if dataset_id:
        request.app.state.auth.require_dataset(user, dataset_id)
    return request.app.state.store.history(user.id, user.role == 'admin', limit, offset, dataset_id, status)


def _detail(request: Request, query_id: str, user: Principal):
    detail = request.app.state.store.detail(query_id, user.id, user.role == 'admin')
    request.app.state.auth.require_dataset(user, detail['dataset_id'])
    return detail


@router.get('/query/{query_id}')
def query_detail(query_id: str, request: Request, user: Principal = Depends(principal)):
    return _detail(request, query_id, user)


@router.post('/query/{query_id}/feedback')
def feedback(query_id: str, payload: FeedbackRequest, request: Request, user: Principal = Depends(principal)):
    _detail(request, query_id, user)
    request.app.state.store.feedback(query_id, user.id, user.role == 'admin', payload.label, payload.comment)
    return {'status': 'recorded'}


@router.get('/query/{query_id}/export')
def export_result(query_id: str, request: Request, format: str = Query(default='csv', pattern='^(csv|xlsx)$'),
                  user: Principal = Depends(principal)):
    detail = _detail(request, query_id, user)
    result = detail['response'].result
    if detail['response'].status != 'verified' or result is None:
        raise ApiError(409, 'result_unavailable', 'No verified result to export')
    filename = 'query_' + re.sub(r'[^A-Za-z0-9_-]', '', query_id) + '.' + format
    def safe(value):
        return "'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value
    if format == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([safe(column) for column in result.columns])
        writer.writerows([[safe(value) for value in row] for row in result.rows])
        data, media_type = output.getvalue().encode('utf-8-sig'), 'text/csv; charset=utf-8'
    else:
        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet('Result')
        sheet.append([safe(column) for column in result.columns])
        for row in result.rows:
            sheet.append([safe(value) for value in row])
        output = io.BytesIO()
        workbook.save(output)
        data, media_type = output.getvalue(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    return Response(data, media_type=media_type, headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@router.get('/metrics')
def metrics(request: Request, user: Principal = Depends(principal)):
    request.app.state.auth.require_admin(user)
    return request.app.state.metrics.snapshot()
