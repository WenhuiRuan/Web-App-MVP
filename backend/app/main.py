import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .config import Settings, load_settings
from .contracts import Contract, ErrorResponse
from .database import Database
from .model_gateway import DeterministicModelGateway

logger = logging.getLogger('panel')


class LiveResponse(Contract):
    status: Literal['ok'] = 'ok'


class ReadyResponse(Contract):
    status: Literal['ready'] = 'ready'
    database: Literal['ready'] = 'ready'
    model_mode: Literal['mock'] = 'mock'


class SystemInfo(Contract):
    name: Literal['AI Panel Studio'] = 'AI Panel Studio'
    version: Literal['0.2.0'] = '0.2.0'
    phase: Literal[2] = 2
    model_mode: Literal['mock', 'unavailable']
    discussion_engine_available: Literal[False] = False


class ApplicationError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False):
        self.status, self.code, self.message, self.retryable = status, code, message, retryable


def error_response(request: Request, status: int, code: str, message: str, retryable=False):
    request_id = getattr(request.state, 'request_id', uuid4())
    return JSONResponse(status_code=status, content={'error': {'code': code, 'message': message, 'retryable': retryable, 'request_id': str(request_id), 'details': []}}, headers={'X-Request-ID': str(request_id)})


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or load_settings()
    database = Database(config.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.migrate()
        app.state.database = database
        app.state.model_gateway = DeterministicModelGateway() if config.model_provider == 'mock' else None
        yield

    app = FastAPI(title='AI Panel Studio — foundation API', version='0.2.0', lifespan=lifespan,
                  responses={422: {'model': ErrorResponse}, 500: {'model': ErrorResponse}})

    @app.middleware('http')
    async def request_context(request: Request, call_next):
        request.state.request_id = uuid4()
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            response = error_response(request, 500, 'INTERNAL_ERROR', '服务暂时无法完成请求。')
        response.headers['X-Request-ID'] = str(request.state.request_id)
        route = request.scope.get('route')
        record = {'request_id': str(request.state.request_id), 'method': request.method,
                  'route': getattr(route, 'path', '<unmatched>'), 'status': response.status_code,
                  'duration_ms': round((time.perf_counter() - start) * 1000, 2)}
        logger.info(json.dumps(record, ensure_ascii=False))
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, _exc):
        return error_response(request, 422, 'VALIDATION_ERROR', '参数格式不符合接口契约。')

    @app.exception_handler(ApplicationError)
    async def application_error(request, exc):
        return error_response(request, exc.status, exc.code, exc.message, exc.retryable)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        code = {404: 'NOT_FOUND', 405: 'METHOD_NOT_ALLOWED'}.get(exc.status_code, 'HTTP_ERROR')
        response = error_response(request, exc.status_code, code, '接口不存在或不支持此请求。')
        if exc.status_code == 405 and exc.headers and 'Allow' in exc.headers:
            response.headers['Allow'] = exc.headers['Allow']
        return response

    @app.get('/api/health/live', response_model=LiveResponse)
    def live():
        return LiveResponse()

    @app.get('/api/health/ready', response_model=ReadyResponse, responses={503: {'model': ErrorResponse}})
    def ready(request: Request):
        if not request.app.state.database.ready():
            raise ApplicationError(503, 'DATABASE_UNAVAILABLE', '数据库尚未就绪。', True)
        if request.app.state.model_gateway is None:
            raise ApplicationError(503, 'MODEL_NOT_CONFIGURED', '真实模型适配尚未实现，请使用 mock 模式。')
        return ReadyResponse()

    @app.get('/api/system', response_model=SystemInfo)
    def system_info():
        return SystemInfo(model_mode='mock' if config.model_provider == 'mock' else 'unavailable')

    return app
