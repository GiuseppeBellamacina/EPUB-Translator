"""Pydantic models for API request/response schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --- Provider ---


class ProviderParams(BaseModel):
    """Per-provider overrides of the translation defaults (validated: they drive every job)."""

    model_config = ConfigDict(extra="allow")

    requests_per_second: float | None = Field(None, ge=0)  # 0 = unlimited
    max_concurrency: int | None = Field(None, ge=1, le=16)  # chapters in parallel
    max_retries: int | None = Field(None, ge=0, le=20)
    structured_output_method: Literal["function_calling", "json_mode", "json_schema"] | None = None


def _clean_params(value: dict | None) -> dict | None:
    return None if value is None else ProviderParams(**value).model_dump(exclude_none=True)


class ProviderCreate(BaseModel):
    name: str
    provider_type: str  # openai, anthropic, openrouter, ollama, custom
    api_key: str | None = None
    base_url: str | None = None
    default_model: str | None = None
    params: dict | None = None

    _params = field_validator("params")(_clean_params)


class ProviderUpdate(BaseModel):
    """Fields left out are unchanged; ``api_key`` None keeps the stored key, "" clears it."""

    name: str | None = None
    provider_type: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    default_model: str | None = None
    params: dict | None = None

    _params = field_validator("params")(_clean_params)


class ProviderModelsRequest(BaseModel):
    provider_type: str
    api_key: str | None = None
    base_url: str | None = None


class ProviderResponse(BaseModel):
    id: int
    name: str
    provider_type: str
    base_url: str | None
    default_model: str | None
    params: dict | None
    is_active: bool
    source: str = "user"  # 'config' = managed by config.yaml

    @field_validator("source", mode="before")
    @classmethod
    def _legacy_source(cls, value):
        return value or "user"

    class Config:
        from_attributes = True


# --- Book ---


class BookResponse(BaseModel):
    id: int
    filename: str
    source_language: str
    target_language: str
    status: str
    total_chapters: int
    translated_chapters: int
    created_at: datetime

    class Config:
        from_attributes = True


class BookDetailResponse(BookResponse):
    chapters: list["ChapterResponse"] = []


class ChapterResponse(BaseModel):
    id: int
    item_id: str
    title: str | None
    order_index: int
    status: str
    has_original: bool = False
    has_translation: bool = False

    class Config:
        from_attributes = True


# --- Translation ---


class TranslateRequest(BaseModel):
    provider_id: int
    source_language: str = "english"
    target_language: str = "italian"
    model: str | None = None  # Override provider's default model
    temperature: float | None = None
    max_tokens: int | None = None


# --- Glossary ---


class GlossaryEntryResponse(BaseModel):
    id: int
    source_term: str
    target_term: str
    context: str | None
    do_not_translate: bool
    user_edited: bool

    class Config:
        from_attributes = True


class GlossaryEntryCreate(BaseModel):
    source_term: str
    target_term: str
    context: str | None = None
    do_not_translate: bool = False


class GlossaryUpdate(BaseModel):
    entries: list[GlossaryEntryCreate]


# --- Test ---


class TestConnectionRequest(BaseModel):
    provider_type: str
    api_key: str | None = None
    base_url: str | None = None
    model: str
    temperature: float = 0.0
