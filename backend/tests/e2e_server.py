"""Loopback-only test server. Fault controls are never mounted by production create_app."""
import asyncio
import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

import uvicorn
from pydantic import BaseModel, ConfigDict, Field

from backend.app.config import Settings, PROJECT_ROOT
from backend.app.main import create_app
from backend.app.model_gateway import DeterministicModelGateway


class Control(BaseModel):
    model_config = ConfigDict(extra='forbid')
    delay: float = Field(default=.08, ge=0, le=1)
    stop_after: int = Field(default=8, ge=2, le=40)
    pause_after: int | None = Field(default=None, ge=0, le=40)
    summary_fails: bool = False
    insights_fail_from: int | None = Field(default=None, ge=1)
    long_content: bool = False
    stream_fault: Literal['gap', 'duplicate', 'disconnect'] | None = None


class BrowserGateway(DeterministicModelGateway):
    def __init__(self):
        self.controls: dict[UUID, Control] = {}
        self.calls: list[dict] = []

    async def generate(self, request):
        control = self.controls.get(request.discussion_id, Control())
        self.calls.append({'discussion_id': str(request.discussion_id), 'run_id': str(request.run_id) if request.run_id else None, 'task': request.task, 'through_turn': request.through_turn})
        if request.task == 'utterance':
            while control.pause_after is not None and len(request.messages) >= control.pause_after:
                await asyncio.sleep(.01)
                control = self.controls.get(request.discussion_id, Control())
        await asyncio.sleep(control.delay)
        label = ''.join(c for c in request.topic[:45] if c not in '。！？!?.\n\r')
        if request.task == 'host_control':
            return {'task': 'host_control', 'action': 'end' if len(request.messages) >= control.stop_after else 'linking' if len(request.messages) % 3 == 0 else 'continue', 'public_focus': f'公开关注：{label}的适用条件'}
        if request.task == 'summary' and control.summary_fails:
            return {'task': 'summary', 'content': '{"private":"not a natural summary"}'}
        if request.task == 'insights' and control.insights_fail_from is not None and request.through_turn >= control.insights_fail_from:
            return {'task': 'insights', 'items': [{'id': 'invalid-source'}]}
        result = await super().generate(request)
        raw = result.model_dump(mode='json')
        if request.task == 'utterance':
            actor = next(p for p in request.participants if p.id == request.actor_id)
            detail = '需要分别记录执行成本与适用条件，并用小规模试点检验风险边界，所有结论仍需核对正式来源与真实证据' if control.long_content else '需要核对适用条件与证据'
            raw['sentences'] = [f'围绕「{label}」第{len(request.messages)+1}条，从{actor.stance}出发，{detail}。', '这是确定性模型的工程演示内容。']
        if request.task == 'insights':
            for item in raw['items']: item['content'] = f'「{label}」的两位专家均明确声明其发言是工程演示内容。'
        return raw


def create_test_app():
    work = PROJECT_ROOT / 'work'; work.mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='stage5-e2e-', dir=work))
    settings = Settings(_env_file=None, database_path=directory / 'panel.sqlite3', model_provider='mock',
                        model_api_key='stage5-backend-secret-sentinel', discussion_max_turns=40,
                        model_timeout_seconds=30, discussion_max_seconds=120)
    app = create_app(settings)
    gateway = BrowserGateway()
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original(application):
            application.state.model_gateway = gateway
            yield
    app.router.lifespan_context = lifespan

    consumed_faults = set()

    @app.middleware('http')
    async def stream_fault(request, call_next):
        response = await call_next(request)
        parts = request.url.path.split('/')
        if len(parts) != 5 or parts[-1] != 'events' or response.status_code != 200:
            return response
        did = UUID(parts[-2])
        source = response.body_iterator
        async def body():
            try:
                async for chunk in source:
                    option = gateway.controls.get(did, Control()).stream_fault
                    marker = (did, option)
                    text = chunk.decode('utf-8') if isinstance(chunk, bytes) else chunk
                    if option and marker not in consumed_faults and 'data: ' in text:
                        consumed_faults.add(marker)
                        if option == 'gap': continue
                        if option == 'disconnect': return
                        yield chunk
                    yield chunk
            finally:
                await source.aclose()
        response.body_iterator = body()
        return response

    @app.post('/api/_test/control/{discussion_id}')
    def control(discussion_id: UUID, body: Control):
        app.state.repository.snapshot(discussion_id)
        gateway.controls[discussion_id] = body
        return {'status': 'configured'}

    @app.get('/api/_test/calls/{discussion_id}')
    def calls(discussion_id: UUID):
        return [c for c in gateway.calls if c['discussion_id'] == str(discussion_id)]

    (work / 'stage5-e2e-last.json').write_text(json.dumps({'directory': str(directory), 'database': str(settings.database_path)}), encoding='utf-8')
    return app


if __name__ == '__main__':
    uvicorn.run(create_test_app(), host='127.0.0.1', port=18081, workers=1, timeout_graceful_shutdown=5, access_log=False, log_level='warning')
