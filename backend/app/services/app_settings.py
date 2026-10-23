"""
App settings changed from the UI, kept in ``data/settings.json`` (config.yaml is
read-only, and these are runtime choices, not deployment ones).
"""

import json

from pydantic import BaseModel, Field

from app.core.config import settings


class AppSettings(BaseModel):
    max_parallel_books: int = Field(1, ge=1, le=8)  # books translated at the same time


def _path():
    return settings.data_dir / "settings.json"


def load() -> AppSettings:
    try:
        return AppSettings(**json.loads(_path().read_text()))
    except (OSError, ValueError):  # missing or unreadable: defaults
        return AppSettings()


def save(value: AppSettings) -> None:
    _path().write_text(value.model_dump_json(indent=2))
