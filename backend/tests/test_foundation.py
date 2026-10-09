import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.contracts import CreateDiscussion
from backend.app.main import create_app


def test_health_and_secret_boundary(tmp_path, caplog):
    sentinel = 'stage2-secret-sentinel-keep-private'
    settings = Settings(_env_file=None, database_path=tmp_path / 'test.db', model_api_key=sentinel)
    assert sentinel not in repr(settings)
    app = create_app(settings)

    @app.get('/test/raise')
    def fail():
        raise RuntimeError(sentinel)

    @app.post('/test/validate')
    def validate(body: CreateDiscussion):
        return body

    with caplog.at_level(logging.INFO, logger='panel'), TestClient(app, raise_server_exceptions=False) as client:
        assert client.get('/api/health/live').status_code == 200
        assert client.get('/api/health/ready').json()['database'] == 'ready'
        info = client.get('/api/system').json()
        assert info['model_mode'] == 'mock'
        assert info['discussion_engine_available'] is False
        for path, code in [('/missing?' + sentinel, 404), ('/test/raise', 500)]:
            response = client.get(path, headers={'X-Request-ID': sentinel})
            assert response.status_code == code
            UUID(response.json()['error']['request_id'])
            assert sentinel not in response.text
            assert sentinel not in str(response.headers)
        invalid = client.post('/test/validate', json={'topic': sentinel, 'expert_count': 99})
        assert invalid.status_code == 422
        assert invalid.json()['error']['code'] == 'VALIDATION_ERROR'
        assert sentinel not in invalid.text
        assert client.post('/api/health/live').json()['error']['code'] == 'METHOD_NOT_ALLOWED'
        assert sentinel not in client.get('/openapi.json').text
    assert sentinel not in caplog.text


def test_unimplemented_provider_reports_not_ready(tmp_path):
    settings = Settings(_env_file=None, database_path=tmp_path / 'test.db', model_provider='later-provider')
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/health/live').status_code == 200
        response = client.get('/api/health/ready')
        assert response.status_code == 503
        assert response.json()['error']['code'] == 'MODEL_NOT_CONFIGURED'


def test_settings_environment_precedes_file_and_frontend_gets_no_config(tmp_path, monkeypatch):
    env = tmp_path / 'settings.env'
    env.write_text('MODEL_PROVIDER=mock\nMODEL_API_KEY=file-value\n', encoding='utf-8')
    monkeypatch.setenv('MODEL_API_KEY', 'environment-value')
    settings = Settings(_env_file=env, database_path=tmp_path / 'test.db')
    assert settings.model_api_key.get_secret_value() == 'environment-value'
    assert 'model_api_key' not in settings.model_dump()


def test_readiness_detects_unavailable_database(tmp_path):
    settings = Settings(_env_file=None, database_path=tmp_path / 'test.db')
    with TestClient(create_app(settings)) as client:
        client.app.state.database.path = tmp_path / 'missing.db'
        response = client.get('/api/health/ready')
        assert response.status_code == 503
        assert response.json()['error']['code'] == 'DATABASE_UNAVAILABLE'
        assert not (tmp_path / 'missing.db').exists()
