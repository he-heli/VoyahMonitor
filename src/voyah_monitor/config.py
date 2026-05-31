from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    voyah_phone: str = Field(default="+7", alias="VOYAH_PHONE")
    voyah_session_path: Path = Field(
        default=Path("data/session.json"),
        alias="VOYAH_SESSION_PATH",
    )
    voyah_network_capture_path: Path = Field(
        default=Path("data/network_capture.json"),
        alias="VOYAH_NETWORK_CAPTURE_PATH",
    )
    voyah_db_path: Path = Field(
        default=Path("data/voyah_monitor.db"),
        alias="VOYAH_DB_PATH",
    )
    voyah_base_url: str = Field(
        default="https://app.voyahassist.ru",
        alias="VOYAH_BASE_URL",
    )
    voyah_allowed_get_paths: str = Field(default="", alias="VOYAH_ALLOWED_GET_PATHS")
    voyah_allowed_post_paths: str = Field(default="", alias="VOYAH_ALLOWED_POST_PATHS")
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_allowed_user_ids: str = Field(default="", alias="TELEGRAM_ALLOWED_USER_IDS")
    telegram_poll_interval: int = Field(default=14400, alias="TELEGRAM_POLL_INTERVAL")
    telegram_poll_jitter: float = Field(default=0.25, alias="TELEGRAM_POLL_JITTER")

    @field_validator("voyah_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def allowed_get_paths(self) -> set[str]:
        return self._parse_paths(self.voyah_allowed_get_paths)

    @property
    def allowed_post_paths(self) -> set[str]:
        return self._parse_paths(self.voyah_allowed_post_paths)

    @property
    def telegram_user_ids(self) -> set[int]:
        if not self.telegram_allowed_user_ids.strip():
            return set()
        return {
            int(part.strip())
            for part in self.telegram_allowed_user_ids.split(",")
            if part.strip()
        }

    @staticmethod
    def _parse_paths(raw: str) -> set[str]:
        if not raw.strip():
            return set()
        return {part.strip() for part in raw.split(",") if part.strip()}


def get_settings() -> Settings:
    return Settings()
