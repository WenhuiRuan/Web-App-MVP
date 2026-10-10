"""Validate curated rosters or import them offline; never calls a model or loads .env."""
import argparse
import json
from pathlib import Path
from uuid import UUID

from backend.app.contracts import CreateDiscussion, Participant, check_roster
from backend.app.database import Database
from backend.app.repository import DiscussionRepository, timestamp

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLES = ROOT / 'data/samples/final/rosters.json'


def load_samples(path=DEFAULT_SAMPLES):
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    if document['format'] != 'ai-panel-studio-rosters-v1':
        raise ValueError('unknown sample format')
    samples = document['samples']
    if len({s['discussion_id'] for s in samples}) != len(samples):
        raise ValueError('duplicate discussion')
    identities = set()
    for sample in samples:
        did = UUID(sample['discussion_id'])
        body = CreateDiscussion.model_validate(sample['create'])
        people = tuple(Participant.model_validate(p) for p in sample['participants'])
        check_roster(people, body.expert_count)
        if any(p.discussion_id != did or p.roster_revision != 1 for p in people):
            raise ValueError('sample scope mismatch')
        if identities.intersection(p.id for p in people):
            raise ValueError('shared participant identity')
        identities.update(p.id for p in people)
        if not sample['source'] or not sample['quality']:
            raise ValueError('missing provenance')
    return samples


def import_samples(database, samples):
    repo = DiscussionRepository(database)
    imported = skipped = 0
    # One transaction for the entire batch, including its public event history.
    with repo.transaction() as conn:
        for sample in samples:
            did = sample['discussion_id']
            existing = conn.execute('SELECT * FROM discussions WHERE id=?', (did,)).fetchone()
            if existing:
                people = [dict(r) for r in conn.execute(
                    'SELECT id,discussion_id,roster_revision,kind,name,title,stance,color '
                    'FROM participants WHERE discussion_id=? AND roster_revision=1', (did,))]
                if (existing['topic'] != sample['create']['topic'] or
                    existing['expert_count'] != sample['create']['expert_count'] or
                    sorted(people, key=lambda p: p['id']) != sorted(sample['participants'], key=lambda p: p['id'])):
                    raise ValueError('sample conflict: existing content retained')
                skipped += 1
                continue
            at = timestamp()
            conn.execute('INSERT INTO discussions(id,topic,expert_count,created_at,updated_at) VALUES (?,?,?,?,?)',
                         (did, sample['create']['topic'], sample['create']['expert_count'], at, at))
            repo._event(conn, did, 'discussion.state_changed', {'state': 'DRAFT', 'version': 0, 'failure_stage': None})
            conn.execute('INSERT INTO rosters(discussion_id,revision) VALUES (?,1)', (did,))
            for person in sample['participants']:
                conn.execute('INSERT INTO participants(id,discussion_id,roster_revision,kind,name,title,stance,color) VALUES (?,?,?,?,?,?,?,?)',
                             tuple(person[k] for k in ('id','discussion_id','roster_revision','kind','name','title','stance','color')))
            conn.execute('UPDATE discussions SET roster_revision=1 WHERE id=?', (did,))
            repo._event(conn, did, 'roster.ready', {'roster_revision': 1, 'participants': sample['participants']})
            repo._transition(conn, did, 'READY')
            repo._snapshot(conn, did)
            imported += 1
    return {'imported': imported, 'skipped': skipped}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument('--database', type=Path, help='Explicit SQLite path; stop its owning service first')
    args = parser.parse_args()
    samples = load_samples(args.file)
    if args.database:
        database = Database(args.database.resolve())
        database.migrate()
        print(json.dumps(import_samples(database, samples)))
    else:
        print(f'Validated {len(samples)} topic/roster samples; no database or model accessed.')


if __name__ == '__main__':
    main()
