"""Opt-in real-service validation server; no test model or production fault endpoints.

Run from the project root: python -m scripts.real_validation_server.
The existing .env supplies the model; inherit PANEL_API_KEY before launching.
Outputs safe call metrics to ignored work/; optional public inputs/final answers,
never headers, credentials or reasoning_content.
"""
import argparse
import json
import hashlib
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import uvicorn

from backend.app.config import load_settings
from backend.app.deepseek_gateway import missing_configuration
from backend.app.main import create_app


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--label',default='stage6a-real',choices=['stage6a-real','stage6a-corrected','stage6a-final','stage6a-final-thinking','stage6a-accepted','stage6a-accepted-final','stage6a-budget-final','stage6c-interaction'])
    parser.add_argument('--max-turns',type=int,choices=[8,12,20],default=12,help='Bounded validation discussion, not a production default')
    parser.add_argument('--capture-final-answers',action='store_true',help='Opt-in public validation evidence, never headers or reasoning')
    args=parser.parse_args()
    settings=load_settings()
    missing=missing_configuration(settings)
    if settings.model_provider!='deepseek' or missing:
        raise SystemExit('Real model configuration unavailable: '+', '.join(missing or ['MODEL_PROVIDER']))
    directory=Path('work');directory.mkdir(exist_ok=True)
    database=directory/f'{args.label}-{uuid4().hex}.sqlite3'
    # Validate a bounded first run, preserving the application's normal time/IO budgets.
    settings=settings.model_copy(update={'database_path':database,'backend_port':18082,'discussion_max_turns':args.max_turns})
    app=create_app(settings)
    original=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async with original(application):
            info={'database':str(database.resolve()),'port':18082,
                'budgets':{k:getattr(settings,k) for k in ('model_timeout_seconds','insight_max_seconds','summary_max_seconds','discussion_max_seconds')},
                'thinking_mode':settings.model_thinking_mode,'reasoning_effort':settings.model_reasoning_effort,
                'code_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                'dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),
                'prompt_sha256_utf8_normalized':{p.name:hashlib.sha256(p.read_text(encoding='utf-8').encode()).hexdigest()
                    for p in sorted(Path('backend/prompts').glob('*.md'))}}
            (directory/f'{args.label}-last.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
            journal=directory/f'{database.stem}-calls.jsonl'
            def export(metric):
                # Flush every completed attempt; a forced process stop cannot erase prior usage.
                with journal.open('a',encoding='utf-8') as file:
                    file.write(json.dumps(metric,ensure_ascii=False)+'\n')
            application.state.model_gateway.metrics_sink=export
            if args.capture_final_answers:
                async def capture(response):
                    await response.aread()
                    if response.status_code!=200: return
                    body=json.loads(response.request.content)
                    payload=response.json()
                    value={'request':{key:body[key] for key in ('model','thinking','response_format','messages')},
                        'final_answers':[choice['message'].get('content') for choice in payload.get('choices',[])]}
                    with (directory/f'{database.stem}-public.jsonl').open('a',encoding='utf-8') as file:
                        file.write(json.dumps(value,ensure_ascii=False)+'\n')
                application.state.model_gateway.client.event_hooks['response'].append(capture)
            try: yield
            finally:
                gateway=application.state.model_gateway
                (directory/f'{args.label}-calls.json').write_text(json.dumps(list(gateway.metrics),ensure_ascii=False,indent=2),encoding='utf-8')
    app.router.lifespan_context=lifespan
    uvicorn.run(app,host='127.0.0.1',port=18082,workers=1,access_log=False,log_level='warning',timeout_graceful_shutdown=5)


if __name__=='__main__':main()
