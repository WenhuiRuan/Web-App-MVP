"""Validate the prerecorded UI fixture against the frozen public contract."""
import json
from pathlib import Path

from backend.app.contracts import EventAdapter, Snapshot
from scripts.export_frontend_demo import build_demo


def test_frontend_fixture_matches_generator_and_contract():
    fixture = json.loads((Path(__file__).parents[2] / 'data/samples/frontend-demo.json').read_text(encoding='utf-8'))
    assert fixture == build_demo()
    Snapshot.model_validate(fixture['initial'])
    events = [EventAdapter.validate_python(e) for group in fixture['groups'] for e in group]
    assert [e.seq for e in events] == list(range(6, 6 + len(events)))
    messages = {str(e.payload.id): e.payload for e in events if e.type == 'turn.committed'}
    assert len(messages) == 16
    assert {m.kind for m in messages.values()} == {'opening', 'statement', 'followup', 'linking'}
    host = fixture['profiles'][0]['id']
    updates = [e for e in events if e.type == 'insights.updated']
    assert len(updates) >= 2
    assert updates[0].payload.through_turn >= 3
    for update in updates:
        items = update.payload.items
        assert len({i.id for i in items}) == len(items)
        for insight in items:
            sources = [messages[str(id)] for id in insight.source_message_ids]
            assert len(sources) >= 2
            assert all(str(m.participant_id) != host and m.turn_no <= update.payload.through_turn for m in sources)
    assert events[-1].payload.state == 'COMPLETED'
    assert fixture['summary']['through_turn'] == 16
