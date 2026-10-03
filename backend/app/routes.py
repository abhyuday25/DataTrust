from fastapi import APIRouter, Depends, File, Request, UploadFile

from app.schemas import DatasetSchema, DatasetSummary
from app.service import DatasetService
from app.core import ApiError
from app.query_models import QueryRequest, QueryResponse


router = APIRouter()


def service(request: Request) -> DatasetService:
    return request.app.state.datasets


@router.get('/health')
def health():
    return {'status': 'ok'}


@router.post('/datasets/upload', response_model=DatasetSchema, status_code=201)
async def upload(file: UploadFile = File(...), datasets: DatasetService = Depends(service)):
    return await datasets.upload(file)


@router.get('/datasets', response_model=list[DatasetSummary])
def list_datasets(datasets: DatasetService = Depends(service)):
    return datasets.list()


@router.get('/datasets/{dataset_id}/schema', response_model=DatasetSchema)
def dataset_schema(dataset_id: str, datasets: DatasetService = Depends(service)):
    return datasets.schema(dataset_id)


@router.post('/query', response_model=QueryResponse)
def query(payload: QueryRequest, request: Request):
    if request.app.state.query_service is None:
        raise ApiError(503, 'provider_unavailable', 'Configure an AI provider to use queries')
    return request.app.state.query_service.run(payload, request.state.request_id)
