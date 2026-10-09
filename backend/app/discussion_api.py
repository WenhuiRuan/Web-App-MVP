"""HTTP boundary: strict public contracts and durable command replay."""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

from .contracts import CreateDiscussion, DiscussionList, EmptyCommand, ErrorResponse, Operation, OperationAccepted, Snapshot, StartDiscussion

router = APIRouter(prefix='/api/discussions', responses={404:{'model':ErrorResponse},409:{'model':ErrorResponse},503:{'model':ErrorResponse}})
Key = Annotated[UUID, Header(alias='Idempotency-Key')]


@router.post('', status_code=201, response_model=Snapshot)
def create_discussion(body: CreateDiscussion, request: Request, idempotency_key: Key):
    response = request.app.state.repository.create(body, idempotency_key)
    return JSONResponse(response.body, status_code=response.status)


@router.get('', response_model=DiscussionList)
def list_discussions(request: Request, status: Literal['active','all']='active', limit: Annotated[int,Query(ge=1,le=100)]=20, cursor: Annotated[str|None,Query(max_length=1024)]=None):
    return request.app.state.repository.listing(status, limit, cursor)


@router.get('/{discussion_id}', response_model=Snapshot)
def get_snapshot(discussion_id: UUID, request: Request):
    return request.app.state.repository.snapshot(discussion_id)


@router.post('/{discussion_id}/roster-generation', status_code=202, response_model=OperationAccepted)
async def generate_roster(discussion_id: UUID, request: Request, idempotency_key: Key, body: EmptyCommand | None = None):
    response = await request.app.state.tasks.generate(discussion_id, idempotency_key)
    return JSONResponse(response.body, status_code=response.status)


@router.post('/{discussion_id}/start', status_code=202, response_model=OperationAccepted)
async def start_discussion(discussion_id: UUID, body: StartDiscussion, request: Request, idempotency_key: Key):
    response = await request.app.state.tasks.start(discussion_id, body, idempotency_key)
    return JSONResponse(response.body, status_code=response.status)


@router.get('/{discussion_id}/operations/{operation_id}', response_model=Operation)
def get_operation(discussion_id: UUID, operation_id: UUID, request: Request):
    return request.app.state.repository.operation(discussion_id, operation_id)


@router.post('/{discussion_id}/summary-retry',status_code=202,response_model=OperationAccepted)
async def retry_summary(discussion_id: UUID,request: Request,idempotency_key: Key,body: EmptyCommand | None=None):
    response=await request.app.state.tasks.retry_summary(discussion_id,idempotency_key)
    return JSONResponse(response.body,status_code=response.status)
