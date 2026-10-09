"""Check actual browser mock captures; no real engine/SSE claim."""
import json
from pathlib import Path
from backend.app.contracts import EventAdapter, Snapshot


def main():
    source = Path(__file__).resolve().parents[1] / 'work/browser-mock-records.json'
    records = json.loads(source.read_text(encoding='utf-8'))
    events = 0
    for record in records.values():
        snapshot = Snapshot.model_validate(record['snapshot'])
        stream = [EventAdapter.validate_python(e) for e in record['events']]
        assert [e.seq for e in stream] == list(range(1, snapshot.last_event_seq + 1))
        assert all(e.discussion_id == snapshot.discussion.id for e in stream)
        assert all(e.payload.discussion_id == snapshot.discussion.id for e in stream if e.type == 'turn.committed')
        events += len(stream)
    print(f'PASS: {len(records)} actual browser mock snapshots and {events} events match the public contract.')


if __name__ == '__main__':
    main()
