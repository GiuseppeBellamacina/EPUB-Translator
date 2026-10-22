"""WebSocket endpoint for real-time translation progress.

Protocol:
    client → {"action": "start", "provider_id": 1, "source_language": "english",
              "target_language": "italian", "model": "...", "restart": false, ...}
    client → {"action": "stop"}                       (pauses; resumable)
    server → {"event": ..., "chapter_index": ..., "message": ..., "data": {...}}

A job resumes from its checkpoints by default; ``restart: true`` starts over.
Stop and disconnect pause the job, errors mark it failed — both are resumable.
"""

import asyncio
import copy
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.agents.pipeline import TranslationPipeline, TranslationProgress
from app.core.config import settings
from app.core.encryption import decrypt_api_key
from app.core.llm_factory import LLMConfig, create_llm
from app.db.database import async_session
from app.db.models import Book, BookStatus, ProviderConfig
from app.services.chunker import SmartChunker
from app.services.documents import open_document
from app.services.job_store import JobStore
from app.services.translation_service import translate_document

ws_router = APIRouter()

# Track active translation jobs for cancellation
active_jobs: dict[int, TranslationPipeline] = {}

# Bulky payloads persisted server-side but not sent to the client
_SERVER_ONLY_KEYS = {"translated_html", "translations"}


def _client_message(event: TranslationProgress) -> dict:
    return {
        "event": event.event_type,
        "chapter_index": event.chapter_index,
        "total_chapters": event.total_chapters,
        "chunk_index": event.chunk_index,
        "total_chunks": event.total_chunks,
        "message": event.message,
        "data": {k: v for k, v in event.data.items() if k not in _SERVER_ONLY_KEYS},
    }


async def _fail(websocket: WebSocket, message: str) -> None:
    await websocket.send_json({"event": "error", "error": message, "message": message})
    await websocket.close()


@ws_router.websocket("/ws/translate/{book_id}")
async def translate_ws(websocket: WebSocket, book_id: int):
    await websocket.accept()
    try:
        data = await websocket.receive_json()
    except WebSocketDisconnect:
        return

    if data.get("action") != "start":
        return await _fail(websocket, "Expected 'start' action")
    if book_id in active_jobs:
        return await _fail(websocket, "A translation is already running for this book")

    async with async_session() as db:
        provider = await db.get(ProviderConfig, data.get("provider_id"))
        book = await db.get(Book, book_id)
    if not provider:
        return await _fail(websocket, "Provider not found")
    if not book:
        return await _fail(websocket, "Book not found")

    params = provider.params or {}
    llm_config = LLMConfig(
        provider=provider.provider_type,
        model=data.get("model") or provider.default_model or "gpt-4o-mini",
        api_key=decrypt_api_key(provider.api_key_encrypted) if provider.api_key_encrypted else None,
        base_url=provider.base_url,
        temperature=data.get("temperature", 0.0),
        max_tokens=data.get("max_tokens"),
        requests_per_second=params.get("requests_per_second", settings.requests_per_second),
        max_retries=params.get("max_retries", settings.llm_max_retries),
        structured_output_method=params.get("structured_output_method"),
    )
    try:
        llm = create_llm(llm_config)
        review_llm = None
        review_model = data.get("review_model")
        if review_model and review_model != llm_config.model:
            # Same provider and key; shares the rate limiter so the job keeps its pace
            review_config = copy.copy(llm_config)
            review_config.model, review_config.requests_per_second = review_model, None
            review_llm = create_llm(review_config)
            review_llm.rate_limiter = llm.rate_limiter
        doc = open_document(book.original_path)
    except Exception as e:
        return await _fail(websocket, f"Failed to start: {e}")

    pipeline = TranslationPipeline(
        llm=llm,
        source_language=data.get("source_language") or book.source_language or "english",
        target_language=data.get("target_language") or book.target_language or "italian",
        chunker=SmartChunker(target_tokens=600, max_tokens=1000, overlap_blocks=2),
        max_retries=1,
        style_instructions=data.get("style_instructions", ""),
        enable_review=data.get("enable_review", settings.enable_review),
        review_llm=review_llm,
    )
    active_jobs[book_id] = pipeline

    store = JobStore(book_id)
    status, output_path, error = BookStatus.failed, None, None
    final_message: dict | None = None

    async def send(message: dict) -> None:
        try:
            await websocket.send_json(message)
        except Exception:
            pass  # client gone: the listener pauses the job, progress is already saved

    async def listen_for_stop() -> None:
        try:
            while True:
                msg = await websocket.receive_json()
                if msg.get("action") == "stop":
                    pipeline.cancel()  # "cancelled" is sent once the pause is persisted
                    return
        except Exception:  # disconnect
            pipeline.cancel()

    listener = asyncio.create_task(listen_for_stop())
    try:
        resume = await store.prepare(doc.units, restart=bool(data.get("restart")))
        pipeline.set_glossary(resume.glossary)
        await store.start(
            provider.provider_type,
            llm_config.model,
            {"temperature": llm_config.temperature, "restart": bool(data.get("restart"))},
        )
        await send(
            {
                "event": "started",
                "message": f"Translation started: {pipeline.source_language} → "
                f"{pipeline.target_language}"
                + (
                    f" (resuming: {len(resume.completed)} chapter(s) done)"
                    if resume.previous
                    else ""
                ),
                "data": {"resumed_chapters": sorted(resume.completed)},
            }
        )

        output = settings.translated_dir / f"{book_id}_{Path(book.filename).stem}{doc.suffix}"
        async for event in translate_document(
            doc,
            pipeline,
            output,
            previous=resume.previous,
            completed=resume.completed,
            analysis=resume.analysis,
            max_concurrency=params.get("max_concurrency", settings.max_concurrency),
        ):
            await store.handle(event)
            if event.event_type == "job_complete":
                output_path = event.data["output_path"]
                status = BookStatus.failed if event.data["failed_units"] else BookStatus.completed
                # Final messages are sent only after the DB is updated (below): a client
                # closing on them must not be mistaken for a cancellation.
                listener.cancel()
                final_message = _client_message(event)
            else:
                await send(_client_message(event))

        if pipeline._cancelled and final_message is None:
            status = BookStatus.paused
            final_message = {"event": "cancelled", "message": "Translation paused, progress saved"}
    except Exception as e:
        error = str(e)
        await send({"event": "error", "message": f"Translation failed: {e}"})
    finally:
        listener.cancel()
        active_jobs.pop(book_id, None)
        await store.finish(status, output_path, error)

    if final_message:
        await send(final_message)
    try:
        await websocket.close()
    except Exception:
        pass


@ws_router.post("/api/translate/{book_id}/stop")
async def stop_translation(book_id: int):
    """Stop (pause) an active translation job."""
    pipeline = active_jobs.get(book_id)
    if pipeline:
        pipeline.cancel()
        return {"status": "stopping"}
    return {"status": "no_active_job"}
