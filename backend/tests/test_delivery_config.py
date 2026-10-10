from pathlib import Path

from backend.app.config import Settings


ROOT = Path(__file__).resolve().parents[2]
EXPECTED = dict(model_timeout_seconds=120, insight_max_seconds=240,
                summary_max_seconds=180, discussion_max_seconds=600,
                discussion_max_turns=20, model_thinking_mode='enabled',
                model_reasoning_effort='low', model_thinking_max_tokens=16384)


def test_default_budgets_match_verified_runtime(monkeypatch):
    for name in EXPECTED:
        monkeypatch.delenv(name.upper(), raising=False)
    settings = Settings(_env_file=None)
    assert {name: getattr(settings, name) for name in EXPECTED} == EXPECTED


def test_example_is_safe_and_matches_defaults(monkeypatch):
    for name in EXPECTED:
        monkeypatch.delenv(name.upper(), raising=False)
    settings = Settings(_env_file=ROOT / '.env.example')
    assert {name: getattr(settings, name) for name in EXPECTED} == EXPECTED
    assert settings.model_provider == 'mock'
    assert settings.model_api_key.get_secret_value() == ''


def test_process_override_retains_validation_turn_limit(tmp_path, monkeypatch):
    env = tmp_path / 'example.env'
    env.write_text('DISCUSSION_MAX_TURNS=20\nMODEL_TIMEOUT_SECONDS=120\n')
    monkeypatch.setenv('DISCUSSION_MAX_TURNS', '8')
    monkeypatch.setenv('MODEL_TIMEOUT_SECONDS', '90')
    settings = Settings(_env_file=env)
    assert (settings.discussion_max_turns, settings.model_timeout_seconds) == (8, 90)
