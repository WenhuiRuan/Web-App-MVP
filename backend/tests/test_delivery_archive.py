import pytest

from scripts.build_delivery import audit, permitted


@pytest.mark.parametrize('name', ['backend/runtime.db-wal', 'backend/runtime.sqlite3-shm',
                                  'frontend/runtime.db-journal', 'backend/identity.jks'])
def test_runtime_sidecars_and_key_stores_are_excluded_even_if_tracked(name):
    assert not permitted(name)


def test_archive_audit_rejects_hidden_reasoning_and_credential_patterns():
    with pytest.raises(ValueError, match='reasoning'):
        audit('data/example.json', b'{"message":{"reasoning_content":"must not ship"}}')
    with pytest.raises(ValueError, match='credential'):
        audit('backend/example.py', ('sk-' + '0' * 32).encode())
    audit('data/example.json', b'{"content":"public answer","usage":{"tokens":42}}')
    assert permitted('.env.example') and permitted('db/migrations/006_provider_failure_codes.sql')
    assert not permitted('frontend/.env.local') and not permitted('../.env')
