from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / '.env', env_file_encoding='utf-8', extra='ignore', hide_input_in_errors=True)

    backend_host: Literal['127.0.0.1', 'localhost', '::1'] = '127.0.0.1'
    backend_port: int = Field(default=8000, ge=1024, le=65535)
    database_path: Path = PROJECT_ROOT / 'local-data' / 'panel.sqlite3'
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR'] = 'INFO'
    model_provider: str = 'mock'
    model_base_url: str = Field(default='', repr=False, exclude=True)
    model_name: str = Field(default='', repr=False, exclude=True)
    model_api_key: SecretStr = Field(default=SecretStr(''), repr=False, exclude=True)
    model_timeout_seconds: int = Field(default=30, ge=1, le=120)
    model_thinking_mode: Literal['enabled', 'disabled'] = 'enabled'
    model_reasoning_effort: Literal['low', 'high', 'max'] = 'high'
    model_thinking_max_tokens: int = Field(default=8192, ge=1024, le=32768)
    model_max_concurrency: int = Field(default=4, ge=1, le=16)
    model_max_attempts: int = Field(default=2, ge=1, le=3)
    discussion_max_active: int = Field(default=3, ge=1, le=10)
    discussion_max_turns: int = Field(default=20, ge=1, le=100)
    discussion_max_seconds: int = Field(default=300, ge=10, le=3600)
    summary_max_seconds: int = Field(default=60, ge=1, le=180)
    insight_max_seconds: int = Field(default=15, ge=1, le=60)

    @field_validator('database_path')
    @classmethod
    def absolute_database_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else PROJECT_ROOT / value


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError:
        raise SystemExit('Configuration invalid; check variable names and ranges in .env.example.') from None
