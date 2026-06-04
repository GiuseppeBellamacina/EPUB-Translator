"""WebSocket endpoint for real-time translation progress."""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.agents.pipeline import TranslationPipeline
from app.core.encryption import decrypt_api_key
from app.core.llm_factory import LLMConfig, create_llm
from app.db.database import async_session
from app.db.models import (
    Book,
    BookStatus,
    Chapter,
    GlossaryEntry,
    ProviderConfig,
    TranslationJob,
)
from app.models.schemas import GlossaryItem
from app.services.chunker import SmartChunker
from app.services.epub_service import EpubService

ws_router = APIRouter()

# Track active translation jobs for cancellation
active_jobs: dict[int, TranslationPipeline] = {}


@ws_router.websocket("/ws/translate/{book_id}")
async def translate_ws(websocket: WebSocket, book_id: int):
    """
    WebSocket endpoint for real-time translation with progress updates.

    Client sends: {"action": "start", "provider_id": 1, "source_language": "english",
                   "target_language": "italian", "model": "gpt-4o-mini"}
    Server sends: progress events as JSON
    """
    await websocket.accept()

    try:
        # Wait for start command
        data = await websocket.receive_json()

        if data.get("action") != "start":
            await websocket.send_json({"error": "Expected 'start' action"})
            await websocket.close()
            return

        # Get provider config
        async with async_session() as db:
            provider_result = await db.execute(
                select(ProviderConfig).where(ProviderConfig.id == data["provider_id"])
            )
            provider = provider_result.scalar_one_or_none()
            if not provider:
                await websocket.send_json({"error": "Provider not found"})
                await websocket.close()
                return

            # Get book
            book_result = await db.execute(select(Book).where(Book.id == book_id))
            book = book_result.scalar_one_or_none()
            if not book:
                await websocket.send_json({"error": "Book not found"})
                await websocket.close()
                return

            # Get existing glossary
            glossary_result = await db.execute(
                select(GlossaryEntry).where(GlossaryEntry.book_id == book_id)
            )
            existing_glossary = [
                GlossaryItem(
                    source_term=e.source_term,
                    target_term=e.target_term,
                    context=e.context,
                    do_not_translate=e.do_not_translate,
                )
                for e in glossary_result.scalars().all()
            ]

            # Create LLM
            api_key = (
                decrypt_api_key(provider.api_key_encrypted) if provider.api_key_encrypted else None
            )
            llm_config = LLMConfig(
                provider=provider.provider_type,
                model=data.get("model") or provider.default_model or "gpt-4o-mini",
                api_key=api_key,
                base_url=provider.base_url,
                temperature=data.get("temperature", 0.0),
                max_tokens=data.get("max_tokens"),
            )

            try:
                llm = create_llm(llm_config)
            except Exception as e:
                await websocket.send_json({"error": f"Failed to create LLM: {str(e)}"})
                await websocket.close()
                return

            # Create pipeline
            source_lang = data.get("source_language", book.source_language or "english")
            target_lang = data.get("target_language", book.target_language or "italian")

            pipeline = TranslationPipeline(
                llm=llm,
                source_language=source_lang,
                target_language=target_lang,
                chunker=SmartChunker(target_tokens=600, max_tokens=1000, overlap_blocks=2),
                max_retries=1,
                style_instructions=data.get("style_instructions", ""),
            )

            active_jobs[book_id] = pipeline

            # Update book status
            book.status = BookStatus.translating
            await db.commit()

            # Create translation job record
            job = TranslationJob(
                book_id=book_id,
                provider=provider.provider_type,
                model=llm_config.model,
                params={"temperature": llm_config.temperature},
                status="running",
            )
            db.add(job)
            await db.commit()

        # Load EPUB and start translation
        epub_book = EpubService.load_book(book.original_path)

        await websocket.send_json(
            {
                "event": "started",
                "message": f"Translation started: {source_lang} → {target_lang}",
            }
        )

        # Run translation with progress streaming
        try:
            translated_chapters: dict[int, dict] = {}
            output_path: str | None = None
            async for progress in EpubService.translate_book(
                epub_book, pipeline, existing_glossary
            ):
                # Capture per-chapter HTML for preview/DB persistence
                if progress.event_type == "chapter_saved":
                    translated_chapters[progress.data["order_index"]] = {
                        "item_id": progress.data["item_id"],
                        "translated_html": progress.data["translated_html"],
                    }
                elif progress.event_type == "job_complete":
                    output_path = progress.data.get("output_path")

                # Send progress to client (omit bulky HTML payload)
                client_data = progress.data
                if progress.event_type == "chapter_saved":
                    client_data = {k: v for k, v in progress.data.items() if k != "translated_html"}
                await websocket.send_json(
                    {
                        "event": progress.event_type,
                        "chapter_index": progress.chapter_index,
                        "total_chapters": progress.total_chapters,
                        "chunk_index": progress.chunk_index,
                        "total_chunks": progress.total_chunks,
                        "message": progress.message,
                        "data": client_data,
                    }
                )

                # Check for cancel message (non-blocking)
                try:
                    msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.01)
                    if msg.get("action") == "stop":
                        pipeline.cancel()
                        await websocket.send_json(
                            {"event": "cancelled", "message": "Translation cancelled"}
                        )
                        break
                except asyncio.TimeoutError:
                    pass
                except WebSocketDisconnect:
                    pipeline.cancel()
                    return

            # Update book status on completion
            async with async_session() as db:
                book_result = await db.execute(select(Book).where(Book.id == book_id))
                book = book_result.scalar_one_or_none()
                if book and not pipeline._cancelled:
                    book.status = BookStatus.completed
                    if output_path:
                        book.translated_path = output_path
                    book.translated_chapters = len(translated_chapters)

                    # Persist per-chapter translated HTML for preview
                    chapters_result = await db.execute(
                        select(Chapter)
                        .where(Chapter.book_id == book_id)
                        .order_by(Chapter.order_index)
                    )
                    existing_chapters = {c.order_index: c for c in chapters_result.scalars().all()}
                    for order_index, ch_data in translated_chapters.items():
                        chapter = existing_chapters.get(order_index)
                        if chapter:
                            chapter.translated_html = ch_data["translated_html"]
                        else:
                            db.add(
                                Chapter(
                                    book_id=book_id,
                                    item_id=ch_data["item_id"],
                                    order_index=order_index,
                                    translated_html=ch_data["translated_html"],
                                )
                            )

                    # Save glossary to DB
                    for entry in pipeline.glossary:
                        existing = await db.execute(
                            select(GlossaryEntry).where(
                                GlossaryEntry.book_id == book_id,
                                GlossaryEntry.source_term == entry.source_term,
                            )
                        )
                        if not existing.scalar_one_or_none():
                            db.add(
                                GlossaryEntry(
                                    book_id=book_id,
                                    source_term=entry.source_term,
                                    target_term=entry.target_term,
                                    context=entry.context,
                                    do_not_translate=entry.do_not_translate,
                                )
                            )
                    await db.commit()
                elif book:
                    book.status = BookStatus.failed
                    await db.commit()

        except Exception as e:
            await websocket.send_json({"event": "error", "message": str(e)})
            async with async_session() as db:
                book_result = await db.execute(select(Book).where(Book.id == book_id))
                book = book_result.scalar_one_or_none()
                if book:
                    book.status = BookStatus.failed
                    await db.commit()

        finally:
            active_jobs.pop(book_id, None)

    except WebSocketDisconnect:
        if book_id in active_jobs:
            active_jobs[book_id].cancel()
            active_jobs.pop(book_id, None)
    except Exception as e:
        try:
            await websocket.send_json({"event": "error", "message": str(e)})
        except Exception:
            pass


@ws_router.post("/api/translate/{book_id}/stop")
async def stop_translation(book_id: int):
    """Stop an active translation job."""
    pipeline = active_jobs.get(book_id)
    if pipeline:
        pipeline.cancel()
        return {"status": "stopping"}
    return {"status": "no_active_job"}
