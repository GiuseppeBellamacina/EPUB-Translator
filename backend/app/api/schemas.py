"""Pydantic models for API request/response schemas."""

from datetime import datetime

from pydantic import BaseModel

# --- Provider ---


class ProviderCreate(BaseModel):
    name: str
    provider_type: str  # openai, anthropic, ollama, custom
    api_key: str | None = None
    base_url: str | None = None
    default_model: str | None = None
    params: dict | None = None


class ProviderResponse(BaseModel):
    id: int
    name: str
    provider_type: str
    base_url: str | None
    default_model: str | None
    params: dict | None
    is_active: bool

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
