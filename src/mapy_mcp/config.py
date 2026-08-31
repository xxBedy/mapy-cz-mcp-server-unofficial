"""Konfigurace serveru z proměnných prostředí."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Lang = Literal["cs", "de", "el", "en", "es", "fr", "it", "nl", "pl", "pt", "ru", "sk", "tr", "uk"]

LANGUAGES: tuple[str, ...] = (
    "cs",
    "de",
    "el",
    "en",
    "es",
    "fr",
    "it",
    "nl",
    "pl",
    "pt",
    "ru",
    "sk",
    "tr",
    "uk",
)


class Settings(BaseSettings):
    """Nastavení serveru. Všechny proměnné mají prefix ``MAPY_``."""

    model_config = SettingsConfigDict(env_prefix="MAPY_", extra="ignore")

    api_key: str | None = Field(
        default=None,
        description=(
            "API klíč z developer.mapy.com. Bez něj server nastartuje, ale nástroje vrátí chybu."
        ),
    )
    default_lang: Lang = "cs"
    credit_budget: int | None = Field(
        default=None,
        description="Strop kreditů na session. Po překročení nástroje odmítnou volat.",
    )
    base_url: str = "https://api.mapy.com"
    timeout: float = 20.0
    image_dir: Path | None = None

    def redact(self, text: str) -> str:
        """Odstraní API klíč z textu — použít na všechno, co jde do logu nebo do chyby."""
        if self.api_key and self.api_key in text:
            return text.replace(self.api_key, "***")
        return text


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Zahodí nacachovaná nastavení — pro testy."""
    global _settings
    _settings = None
