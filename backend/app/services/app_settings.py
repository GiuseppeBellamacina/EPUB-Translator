"""
App settings changed from the UI, kept in ``data/settings.json`` (config.yaml is
read-only, and these are runtime choices, not deployment ones).
"""

import json

from pydantic import BaseModel, Field

from app.core.config import settings


class AppSettings(BaseModel):
    max_parallel_books: int = Field(1, ge=1, le=8)  # books translated at the same time
    # entries per prompt (0 = all the passage mentions), read at every chunk: changes apply
    # to running jobs too. The passage's own mentions come first, then the text before it.
    max_glossary_terms: int = Field(150, ge=0, le=2000)
    max_compendium_entries: int = Field(60, ge=0, le=1000)

    @property
    def glossary_limit(self) -> int | None:
        return self.max_glossary_terms or None

    @property
    def compendium_limit(self) -> int | None:
        return self.max_compendium_entries or None


def _path():
    return settings.data_dir / "settings.json"


def load() -> AppSettings:
    try:
        return AppSettings(**json.loads(_path().read_text()))
    except (OSError, ValueError):  # missing or unreadable: defaults
        return AppSettings()


def save(value: AppSettings) -> None:
    _path().write_text(value.model_dump_json(indent=2))
