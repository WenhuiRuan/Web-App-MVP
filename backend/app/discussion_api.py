"""HTTP boundary: strict public contracts and durable command replay."""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

from .contracts import CreateDiscussion, DiscussionList, ErrorResponse, Snapshot

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
