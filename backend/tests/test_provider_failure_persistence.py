"""Provider failures must commit task state/events, including on upgraded SQLite."""
import sqlite3
from pathlib import Path
import pytest
from backend.app.database import Database
from backend.tests.test_database import seed
from backend.tests.test_roster_tasks import setup,events
from backend.tests.test_insight_pipeline import prepared, evidence, statement
from backend.tests.test_summary_pipeline import summarizing
from uuid import uuid4

PROVIDER_CODES=['MODEL_REQUEST_INVALID','MODEL_AUTH_FAILED','MODEL_BALANCE_EXHAUSTED','MODEL_NOT_FOUND',
    'MODEL_RATE_LIMITED','MODEL_SERVICE_UNAVAILABLE','MODEL_CONNECTION_FAILED']


@pytest.mark.parametrize('code',PROVIDER_CODES)
def test_provider_insight_failure_is_persisted_and_previous_batch_is_kept(setup,code):
    _,repo,did,rid=prepared(setup)
    previous=repo.claim_insights(did,rid)
    assert repo.complete_insights(previous,evidence(previous.request))
    statement(repo,did,rid,2)
    before=repo.snapshot(did);claim=repo.claim_insights(did,rid)
    assert before.insights.items
    assert repo.fail_insights(claim,code)
    after=repo.snapshot(did)
    assert after.insight_status.state=='FAILED' and after.insight_status.error_code==code
    assert after.messages==before.messages and after.insights==before.insights
    assert after.discussion.state=='RUNNING'


@pytest.mark.parametrize('code',PROVIDER_CODES)
def test_provider_summary_failure_can_retry_same_frozen_run(setup,code):
    client,repo,did,rid=summarizing(setup)
    before=repo.snapshot(did);claim=repo.claim_summary(did,rid)
    assert repo.fail_summary(claim,code)
    failed=repo.snapshot(did)
    assert failed.discussion.state=='FAILED' and failed.discussion.failure_code==code
    assert failed.messages==before.messages and failed.insights==before.insights
    assert events(client,str(did))[-2]['payload']['code']==code
    response,again=repo.admit_summary_retry(did,uuid4(),client.app.state.tasks.settings,True)
    assert response.status==202 and again.request.run_id==rid
    assert again.request.messages==before.messages and again.request.through_turn==len(before.messages)
    assert repo.complete_summary(again,{'task':'summary','content':'主持人总结：原发言与观点保留，当前规则仍为提案。'})
    assert repo.snapshot(did).discussion.state=='COMPLETED'


def test_upgrade_preserves_v5_jobs_and_adds_provider_codes(tmp_path):
    old_dir=tmp_path/'old';old_dir.mkdir()
    for p in (Path(__file__).resolve().parents[2]/'db/migrations').glob('*.sql'):
        if int(p.name[:3])<=5:(old_dir/p.name).write_bytes(p.read_bytes())
    database=Database(tmp_path/'old.sqlite3',migrations_dir=old_dir)
    assert database.migrate()==[1,2,3,4,5]
    seed(database)
    with database.connect() as conn:
        conn.execute("INSERT INTO insight_jobs(id,discussion_id,run_id,version,through_turn) VALUES ('old-i','a','a-r',1,0)")
        conn.execute("INSERT INTO summary_jobs(id,discussion_id,run_id,attempt,through_turn,insight_version) VALUES ('old-s','a','a-r',1,0,0)")
        history=[tuple(r) for r in conn.execute('SELECT version,name,checksum FROM schema_migrations')]
    upgraded=Database(database.path)
    assert upgraded.migrate()==[6] and upgraded.migrate()==[]
    with upgraded.connect() as conn:
        assert [tuple(r) for r in conn.execute('SELECT version,name,checksum FROM schema_migrations WHERE version<=5')]==history
        conn.execute("UPDATE insight_jobs SET state='FAILED',error_code='MODEL_BALANCE_EXHAUSTED' WHERE id='old-i'")
        conn.execute("UPDATE summary_jobs SET status='FAILED',error_code='MODEL_AUTH_FAILED' WHERE id='old-s'")
        assert conn.execute('select count(*) from runs').fetchone()[0]==2
        assert not list(conn.execute('pragma foreign_key_check'))
        conn.execute("INSERT INTO summary_jobs(id,discussion_id,run_id,attempt,through_turn,insight_version) VALUES ('pending','a','a-r',2,0,0)")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO summary_jobs(id,discussion_id,run_id,attempt,through_turn,insight_version) VALUES ('duplicate','a','a-r',3,0,0)")
