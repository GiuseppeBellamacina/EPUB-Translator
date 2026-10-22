"""REST API routes for EPUB Translator."""

import asyncio
import shutil
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    BookDetailResponse,
    BookResponse,
    ChapterResponse,
    GlossaryEntryCreate,
    GlossaryEntryResponse,
    GlossaryUpdate,
    ProviderCreate,
    ProviderModelsRequest,
    ProviderResponse,
    ProviderUpdate,
    TestConnectionRequest,
)
from app.api.websocket import active_jobs, recent_events, run_started
from app.core.bootstrap import load_config
from app.core.config import settings
from app.core.encryption import decrypt_api_key, encrypt_api_key
from app.core.llm_factory import LLMConfig, test_llm_connection
from app.db.database import get_db
from app.db.models import (
    Book,
    BookStatus,
    Chapter,
    ChapterStatus,
    GlossaryEntry,
    ProviderConfig,
    TranslationJob,
)
from app.services.chunker import SmartChunker
from app.services.cost_estimator import DEFAULT_MODELS, TokenProfile, estimate, profile_document
from app.services.documents import open_document
from app.services.html_processor import extract_visible_text
from app.services.model_catalog import list_models, price_for
from app.services.pricing import ModelPrice, PriceTable, get_prices

router = APIRouter()


# === PROVIDERS ===


@router.get("/providers", response_model=list[ProviderResponse])
async def list_providers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProviderConfig).where(ProviderConfig.is_active.is_(True)))
    return result.scalars().all()


@router.post("/providers", response_model=ProviderResponse)
async def create_provider(data: ProviderCreate, db: AsyncSession = Depends(get_db)):
    provider = ProviderConfig(
        name=data.name,
        provider_type=data.provider_type,
        api_key_encrypted=encrypt_api_key(data.api_key) if data.api_key else None,
        base_url=data.base_url,
        default_model=data.default_model,
        params=data.params,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


@router.put("/providers/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: int, data: ProviderUpdate, db: AsyncSession = Depends(get_db)
):
    """Edit a provider. Editing a config.yaml provider makes it user-owned (bootstrap skips it)."""
    provider = await db.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    changes = data.model_dump(exclude_unset=True)
    api_key = changes.pop("api_key", None)
    for field, value in changes.items():
        setattr(provider, field, value)
    if api_key is not None:  # None keeps the stored key, "" clears it
        provider.api_key_encrypted = encrypt_api_key(api_key) if api_key else None
    provider.source = "user"
    await db.commit()
    await db.refresh(provider)
    return provider


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(404, "Provider not found")
    await db.delete(provider)
    await db.commit()
    return {"status": "deleted"}


@router.get("/providers/{provider_id}/models")
async def provider_models(
    provider_id: int, refresh: bool = False, db: AsyncSession = Depends(get_db)
):
    """Chat models the provider serves, listed live from its API (cached a few minutes)."""
    provider = await db.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    api_key = decrypt_api_key(provider.api_key_encrypted) if provider.api_key_encrypted else None
    try:
        return await list_models(
            provider.provider_type, api_key, provider.base_url, await get_prices(), refresh
        )
    except Exception as e:
        raise HTTPException(502, f"Could not list models from {provider.name}: {e}")


@router.post("/providers/models")
async def unsaved_provider_models(data: ProviderModelsRequest):
    """Models of a provider that is not saved yet; a failure also means a bad key or URL."""
    try:
        return await list_models(
            data.provider_type, data.api_key or None, data.base_url or None, await get_prices()
        )
    except Exception as e:
        raise HTTPException(502, f"Could not list models: {e}")


@router.post("/providers/test")
async def test_provider(data: TestConnectionRequest):
    config = LLMConfig(
        provider=data.provider_type,
        model=data.model,
        api_key=data.api_key,
        base_url=data.base_url,
        temperature=data.temperature,
    )
    result = await test_llm_connection(config)
    return result


# === BOOKS ===


SUPPORTED_SUFFIXES = {".epub", ".pdf"}


@router.post("/upload", response_model=BookResponse)
async def upload_book(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(400, "Only .epub and .pdf files are supported")

    # Unique name on disk: two uploads with the same filename must not overwrite each other
    upload_path = settings.uploads_dir / f"{uuid.uuid4().hex[:8]}_{Path(file.filename).name}"
    with open(upload_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        doc = open_document(upload_path)
        info, units = doc.info(), doc.units
    except Exception as e:
        upload_path.unlink(missing_ok=True)
        raise HTTPException(400, f"Invalid {suffix[1:].upper()} file: {e}")

    book = Book(
        filename=Path(file.filename).name,
        original_path=str(upload_path),
        source_language=info.get("language") or "english",
        target_language="italian",
        status=BookStatus.uploaded,
        total_chapters=len(units),
    )
    db.add(book)
    await db.commit()
    await db.refresh(book)

    for i, unit in enumerate(units):
        db.add(
            Chapter(
                book_id=book.id,
                item_id=unit.item_id,
                title=unit.title,
                order_index=i,
                status=ChapterStatus.pending,
            )
        )
    await db.commit()

    return book


@router.get("/books", response_model=list[BookResponse])
async def list_books(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Book).order_by(Book.created_at.desc()))
    return result.scalars().all()


@router.get("/books/{book_id}", response_model=BookDetailResponse)
async def get_book(book_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(404, "Book not found")

    # Get chapters
    chapters_result = await db.execute(
        select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.order_index)
    )
    chapters = chapters_result.scalars().all()

    return BookDetailResponse(
        **{c.name: getattr(book, c.name) for c in Book.__table__.columns},
        chapters=[
            ChapterResponse(
                id=ch.id,
                item_id=ch.item_id,
                title=ch.title,
                order_index=ch.order_index,
                status=ch.status.value if ch.status else "pending",
                has_original=ch.original_html is not None,
                has_translation=ch.translated_html is not None,
            )
            for ch in chapters
        ],
    )


@router.get("/books/{book_id}/preview")
async def get_preview(book_id: int, chapter_index: int = 0, db: AsyncSession = Depends(get_db)):
    """Get side-by-side preview of original vs translated for a chapter (or PDF page)."""
    book = await db.get(Book, book_id)
    if not book:
        raise HTTPException(404, "Book not found")

    doc = open_document(book.original_path)
    if not 0 <= chapter_index < len(doc.units):
        raise HTTPException(400, "Chapter index out of range")

    result = await db.execute(
        select(Chapter).where(Chapter.book_id == book_id, Chapter.order_index == chapter_index)
    )
    chapter = result.scalar_one_or_none()
    translated_text = ""
    if chapter and chapter.translated_html:
        translated_text = extract_visible_text(chapter.translated_html)

    return {
        "chapter_index": chapter_index,
        "total_chapters": len(doc.units),
        "original_text": doc.text(chapter_index),
        "translated_text": translated_text,
        "original_html": doc.render(chapter_index, None) or "",
    }


@router.get("/books/{book_id}/progress")
async def get_progress(book_id: int, db: AsyncSession = Depends(get_db)):
    """Run state of a book's translation, also usable after a page reload."""
    book = await db.get(Book, book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    rows = (
        await db.execute(
            select(Chapter.order_index, Chapter.status).where(Chapter.book_id == book_id)
        )
    ).all()
    completed = sum(status == ChapterStatus.completed for _, status in rows)
    running = book_id in active_jobs
    job = (
        await db.execute(
            select(TranslationJob)
            .where(TranslationJob.book_id == book_id)
            .order_by(TranslationJob.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    eta = None
    if running and book_id in run_started:
        start, done_at_start = run_started[book_id]
        done_now = completed - done_at_start
        if done_now > 0:
            eta = (time.time() - start) / done_now * (book.total_chapters - completed)

    return {
        "status": book.status.value if book.status else "uploaded",
        "running": running,
        "total_units": book.total_chapters,
        "completed_units": completed,
        "failed_units": sorted(i for i, s in rows if s == ChapterStatus.failed),
        "in_flight": (
            sorted(i for i, s in rows if s == ChapterStatus.translating) if running else []
        ),
        "started_at": job.started_at.isoformat() if job and job.started_at else None,
        "eta_seconds": eta,
        "recent_events": list(reversed(recent_events.get(book_id, []))),
    }


@router.get("/books/{book_id}/estimate")
async def estimate_cost(
    book_id: int,
    target_language: str | None = None,
    refresh_prices: bool = False,
    provider_id: int | None = None,
    model: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Estimated translation cost per model, with current prices.

    With ``provider_id`` and ``model``, only that model (empty list if its price is unknown).
    """
    book = await db.get(Book, book_id)
    if not book:
        raise HTTPException(404, "Book not found")

    if book.token_profile is None:
        chunker = SmartChunker(target_tokens=600, max_tokens=1000, overlap_blocks=2)
        profile = await asyncio.to_thread(
            lambda: profile_document(open_document(book.original_path), chunker)
        )
        book.token_profile = asdict(profile)
        await db.commit()
    profile = TokenProfile(**book.token_profile)
    language = target_language or book.target_language
    prices = await get_prices(force_refresh=refresh_prices)

    if provider_id is not None and model:
        provider = await db.get(ProviderConfig, provider_id)
        if not provider:
            raise HTTPException(404, "Provider not found")
        price = price_for(provider.provider_type, model, prices)
        if price is None and provider.provider_type == "custom":
            # OpenAI-compatible routers (OpenRouter) publish prices in their model list
            api_key = (
                decrypt_api_key(provider.api_key_encrypted) if provider.api_key_encrypted else None
            )
            try:
                listed = await list_models("custom", api_key, provider.base_url, prices)
            except Exception:
                listed = []
            option = next((m for m in listed if m["id"] == model), None)
            if option and option["input_per_million"] is not None:
                price = ModelPrice(
                    "openai",
                    option["input_per_million"] / 1e6,
                    option["output_per_million"] / 1e6,
                    reasoning=False,
                )
        if price is None:
            return estimate(profile, prices, language, {})
        single = PriceTable({model: price}, prices.fetched_at, prices.source)
        return estimate(profile, single, language, {price.provider: [model]})

    # Models from config.yaml (pricing.models) plus the defaults of configured providers
    models = {p: list(names) for p, names in DEFAULT_MODELS.items()}
    models.update((load_config().get("pricing") or {}).get("models") or {})
    providers = await db.execute(select(ProviderConfig).where(ProviderConfig.is_active.is_(True)))
    for provider in providers.scalars():
        if provider.provider_type in models and provider.default_model:
            models[provider.provider_type].append(provider.default_model)
    return estimate(profile, prices, language, models)


@router.get("/books/{book_id}/download")
async def download_book(book_id: int, db: AsyncSession = Depends(get_db)):
    from fastapi.responses import FileResponse

    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book or not book.translated_path:
        raise HTTPException(404, "Translated book not found")

    path = Path(book.translated_path)
    if not path.exists():
        raise HTTPException(404, "Translated file not found on disk")

    return FileResponse(
        path=str(path),
        filename=f"translated_{book.filename}",
        media_type="application/pdf" if path.suffix == ".pdf" else "application/epub+zip",
    )


# === GLOSSARY ===


@router.get("/glossary/{book_id}", response_model=list[GlossaryEntryResponse])
async def get_glossary(book_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GlossaryEntry).where(GlossaryEntry.book_id == book_id))
    return result.scalars().all()


@router.put("/glossary/{book_id}")
async def update_glossary(book_id: int, data: GlossaryUpdate, db: AsyncSession = Depends(get_db)):
    # Delete existing entries
    result = await db.execute(select(GlossaryEntry).where(GlossaryEntry.book_id == book_id))
    for entry in result.scalars().all():
        await db.delete(entry)

    # Insert new entries
    for entry_data in data.entries:
        entry = GlossaryEntry(
            book_id=book_id,
            source_term=entry_data.source_term,
            target_term=entry_data.target_term,
            context=entry_data.context,
            do_not_translate=entry_data.do_not_translate,
            user_edited=True,
        )
        db.add(entry)

    await db.commit()
    return {"status": "updated", "count": len(data.entries)}


@router.post("/glossary/{book_id}/entry", response_model=GlossaryEntryResponse)
async def add_glossary_entry(
    book_id: int,
    entry: GlossaryEntryCreate,
    db: AsyncSession = Depends(get_db),
):
    new_entry = GlossaryEntry(
        book_id=book_id,
        source_term=entry.source_term,
        target_term=entry.target_term,
        context=entry.context,
        do_not_translate=entry.do_not_translate,
        user_edited=True,
    )
    db.add(new_entry)
    await db.commit()
    await db.refresh(new_entry)
    return new_entry
