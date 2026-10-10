"""Opt-in real-service validation server; no test model or production fault endpoints.

Run from the project root: python -m scripts.real_validation_server.
The existing .env supplies the model; inherit PANEL_API_KEY before launching.
Outputs safe call metrics to ignored work/, never prompts or reasoning_content.
"""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import uvicorn

from backend.app.config import load_settings
from backend.app.deepseek_gateway import missing_configuration
from backend.app.main import create_app


def main():
    settings=load_settings()
    missing=missing_configuration(settings)
    if settings.model_provider!='deepseek' or missing:
        raise SystemExit('Real model configuration unavailable: '+', '.join(missing or ['MODEL_PROVIDER']))
    directory=Path('work');directory.mkdir(exist_ok=True)
    database=directory/f'stage6a-real-{uuid4().hex}.sqlite3'
    # Validate a bounded first run, preserving the application's normal time/IO budgets.
    settings=settings.model_copy(update={'database_path':database,'backend_port':18082,'discussion_max_turns':12})
    app=create_app(settings)
    original=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async with original(application):
            info={'database':str(database.resolve()),'port':18082}
            (directory/'stage6a-real-last.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
            try: yield
            finally:
                gateway=application.state.model_gateway
                (directory/'stage6a-real-calls.json').write_text(json.dumps(list(gateway.metrics),ensure_ascii=False,indent=2),encoding='utf-8')
    app.router.lifespan_context=lifespan
    uvicorn.run(app,host='127.0.0.1',port=18082,workers=1,access_log=False,log_level='warning',timeout_graceful_shutdown=5)


if __name__=='__main__':main()
