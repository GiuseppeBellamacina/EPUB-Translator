"""Translation jobs and the book queue, run as server tasks.

A job runs independently of any client: WebSocket clients only follow its
messages (``subscribe``), so closing the page does not pause it. Every start
goes through the queue (``queue_items`` table), which runs one book at a time:

- ``enqueue(..., front=True)`` is the single-book start of the translate page
- ``stop`` pauses the current book and halts the queue; ``kick`` resumes it
- a failed book is recorded and the queue moves on
- on startup the interrupted item becomes ``paused`` and the queue waits for a resume
"""

import asyncio
import copy
import logging
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import func, select, update

from app.agents.pipeline import TranslationPipeline, TranslationProgress
from app.core.config import settings
from app.core.encryption import decrypt_api_key
from app.core.llm_factory import LLMConfig, create_llm
from app.db.database import async_session
from app.db.models import Book, BookStatus, ProviderConfig, QueueItem
from app.services.chunker import SmartChunker
from app.services.documents import open_document
from app.services.job_store import JobStore
from app.services.translation_service import translate_document


class RunConfig(BaseModel):
    provider_id: int
    model: str | None = None
    review_model: str | None = None
    enable_review: bool = True
    source_language: str | None = None  # None: the book's own
    target_language: str | None = None
    style_instructions: str = ""
    temperature: float = 0.0
    max_tokens: int | None = None
    restart: bool = False


logger = logging.getLogger(__name__)

# Running pipelines (for stop), per book: recent client messages (a page reload shows
# the latest log), live subscribers and the current run's start (time, units done).
active_jobs: dict[int, TranslationPipeline] = {}
recent_events: dict[int, deque] = {}
run_started: dict[int, tuple[float, int]] = {}
_subscribers: dict[int, set[asyncio.Queue]] = {}
_runner: asyncio.Task | None = None
_halt = False
_halted_at: datetime | None = None  # when the last stop happened

# Bulky payloads persisted server-side but not sent to the client
_SERVER_ONLY_KEYS = {"translated_html", "translations"}
FINAL = None  # sent to subscribers when the book's job is over


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


def publish(book_id: int, message: dict | None) -> None:
    if message is not None:
        message = {**message, "ts": time.time()}
        recent_events.setdefault(book_id, deque(maxlen=200)).append(message)
    for queue in _subscribers.get(book_id, ()):
        queue.put_nowait(message)


def subscribe(book_id: int) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(book_id, set()).add(queue)
    return queue


def unsubscribe(book_id: int, queue: asyncio.Queue) -> None:
    _subscribers.get(book_id, set()).discard(queue)


# --- queue -------------------------------------------------------------------


async def enqueue(
    book_ids: list[int],
    config: RunConfig,
    keep_glossary: bool = False,
    front: bool = False,
    keep_compendium: bool = False,
) -> list[QueueItem]:
    """Add books (a book already waiting gets the new settings and place), then run."""
    async with async_session() as db:
        if not await db.get(ProviderConfig, config.provider_id):
            raise ValueError("Provider not found")
        for book_id in book_ids:
            if not await db.get(Book, book_id):
                raise ValueError(f"Book {book_id} not found")
            if book_id in active_jobs:
                raise ValueError("A translation is already running for this book")
        waiting = await db.execute(
            select(QueueItem).where(
                QueueItem.book_id.in_(book_ids), QueueItem.status.in_(("pending", "paused"))
            )
        )
        for item in waiting.scalars():
            await db.delete(item)
        bounds = (
            await db.execute(select(func.min(QueueItem.position), func.max(QueueItem.position)))
        ).one()
        start = (bounds[0] or 0) - len(book_ids) if front else (bounds[1] or 0) + 1
        items = [
            QueueItem(
                book_id=book_id,
                position=start + i,
                config=config.model_dump(),
                keep_glossary=keep_glossary and i > 0,  # never from an earlier batch
                keep_compendium=keep_compendium and i > 0,
                status="pending",
            )
            for i, book_id in enumerate(book_ids)
        ]
        db.add_all(items)
        await db.commit()
    kick()
    return items


def kick() -> None:
    """Run the queue unless it is already running."""
    global _runner, _halt
    _halt = False
    if _runner is None or _runner.done():
        _runner = asyncio.create_task(_run_queue())  # module reference keeps it alive


def queue_running() -> bool:
    return _runner is not None and not _runner.done()


def stop(book_id: int | None = None) -> bool:
    """Pause the running book (any, or ``book_id``) and halt the queue.

    Books waiting at that moment become ``paused``: only ``resume`` runs them again,
    not a later start of another book.
    """
    global _halt, _halted_at
    targets = [p for b, p in active_jobs.items() if book_id in (None, b)]
    if book_id is None or targets:
        _halt, _halted_at = True, datetime.utcnow()
    for pipeline in targets:
        pipeline.cancel()
    return bool(targets)


async def resume() -> None:
    """Run the paused books again (in their order), then anything else waiting."""
    async with async_session() as db:
        await db.execute(
            update(QueueItem).where(QueueItem.status == "paused").values(status="pending")
        )
        await db.commit()
    kick()


async def _pause_waiting(before: datetime) -> None:
    async with async_session() as db:
        await db.execute(
            update(QueueItem)
            .where(QueueItem.status == "pending", QueueItem.created_at <= before)
            .values(status="paused")
        )
        await db.commit()


async def shutdown() -> None:
    """App shutdown: pause the running book so its state is saved."""
    stop()
    if _runner is not None:
        try:
            await asyncio.wait_for(asyncio.shield(_runner), timeout=20)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        except Exception:  # a crashed runner must not block the shutdown
            logger.exception("Queue runner failed")


async def recover_queue() -> None:
    """Startup: the interrupted queue (running and waiting books) waits for a resume."""
    async with async_session() as db:
        await db.execute(
            update(QueueItem)
            .where(QueueItem.status.in_(("running", "pending")))
            .values(status="paused")
        )
        await db.commit()


async def _next_item() -> QueueItem | None:
    async with async_session() as db:
        result = await db.execute(
            select(QueueItem)
            .where(QueueItem.status == "pending")
            .order_by(QueueItem.position)
            .limit(1)
        )
        return result.scalar_one_or_none()


async def _set_item(item_id: int, status: str, error: str | None = None) -> None:
    async with async_session() as db:
        values: dict = {"status": status, "error": error}
        if status == "running":  # "start over" applies once, not to a later resume
            config = await db.scalar(select(QueueItem.config).where(QueueItem.id == item_id))
            values["config"] = {**(config or {}), "restart": False}
        # a bulk UPDATE: the item may have been removed meanwhile (book deleted)
        await db.execute(update(QueueItem).where(QueueItem.id == item_id).values(**values))
        await db.commit()


async def dequeue(book_id: int) -> bool:
    """Remove a book that is waiting (not running) from the queue."""
    async with async_session() as db:
        result = await db.execute(
            select(QueueItem).where(
                QueueItem.book_id == book_id, QueueItem.status.in_(("pending", "paused"))
            )
        )
        items = list(result.scalars())
        for item in items:
            await db.delete(item)
        await db.commit()
    return bool(items)


async def _previous_book(item: QueueItem) -> int | None:
    async with async_session() as db:
        return await db.scalar(
            select(QueueItem.book_id)
            .where(QueueItem.position < item.position, QueueItem.status.in_(("done", "failed")))
            .order_by(QueueItem.position.desc())
            .limit(1)
        )


async def _run_queue() -> None:
    global _halted_at
    while True:
        if _halted_at:  # a stop: the books waiting then are paused, newer starts still run
            await _pause_waiting(_halted_at)
            _halted_at = None
        if _halt or not (item := await _next_item()):
            break
        await _set_item(item.id, "running")  # item still holds the config read before
        previous = await _previous_book(item)
        try:
            status = await run_job(
                item.book_id,
                RunConfig(**item.config),
                carry_glossary_from=previous if item.keep_glossary else None,
                carry_compendium_from=previous if item.keep_compendium else None,
            )
            error = None
        except Exception as e:  # could not start (provider gone, unreadable file...)
            status, error = BookStatus.failed, str(e)
            publish(item.book_id, {"event": "error", "message": f"Failed to start: {e}"})
            publish(item.book_id, FINAL)
        await _set_item(
            item.id,
            {BookStatus.completed: "done", BookStatus.paused: "paused"}.get(status, "failed"),
            error,
        )


# --- one book ------------------------------------------------------------------


async def run_job(
    book_id: int,
    config: RunConfig,
    carry_glossary_from: int | None = None,
    carry_compendium_from: int | None = None,
) -> BookStatus:
    """Translate one book; returns its final status. Raises only if it cannot start."""
    async with async_session() as db:
        provider = await db.get(ProviderConfig, config.provider_id)
        book = await db.get(Book, book_id)
    if not provider:
        raise ValueError("Provider not found")
    if not book:
        raise ValueError("Book not found")

    params = provider.params or {}
    llm_config = LLMConfig(
        provider=provider.provider_type,
        model=config.model or provider.default_model or "gpt-4o-mini",
        api_key=decrypt_api_key(provider.api_key_encrypted) if provider.api_key_encrypted else None,
        base_url=provider.base_url,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        requests_per_second=params.get("requests_per_second", settings.requests_per_second),
        max_retries=params.get("max_retries", settings.llm_max_retries),
        structured_output_method=params.get("structured_output_method"),
    )
    llm = create_llm(llm_config)
    review_llm = None
    if config.review_model and config.review_model != llm_config.model:
        # Same provider and key; shares the rate limiter so the job keeps its pace
        review_config = copy.copy(llm_config)
        review_config.model, review_config.requests_per_second = config.review_model, None
        review_llm = create_llm(review_config)
        review_llm.rate_limiter = llm.rate_limiter
    doc = open_document(book.original_path)

    pipeline = TranslationPipeline(
        llm=llm,
        source_language=config.source_language or book.source_language or "english",
        target_language=config.target_language or book.target_language or "italian",
        chunker=SmartChunker(target_tokens=600, max_tokens=1000, overlap_blocks=2),
        max_retries=1,
        style_instructions=config.style_instructions,
        enable_review=config.enable_review,
        review_llm=review_llm,
    )
    active_jobs[book_id] = pipeline
    if _halt:  # paused while the book was starting
        pipeline.cancel()
    recent_events[book_id] = deque(maxlen=200)
    store = JobStore(book_id)
    status, output_path, error = BookStatus.failed, None, None
    final_message: dict | None = None

    try:
        resume = await store.prepare(doc.units, restart=config.restart)
        carried = await store.import_glossary(carry_glossary_from) if carry_glossary_from else []
        pipeline.set_glossary(resume.glossary + carried)
        known = (
            await store.import_compendium(carry_compendium_from) if carry_compendium_from else []
        )
        pipeline.set_compendium(resume.compendium_user + known, resume.compendium_learned)
        run_started[book_id] = (time.time(), len(resume.completed))
        # the full config is kept on the job so the UI can show (and resume with) it
        await store.start(provider.provider_type, llm_config.model, config.model_dump())
        publish(
            book_id,
            {
                "event": "started",
                "message": f"Translation started: {pipeline.source_language} → "
                f"{pipeline.target_language}"
                + (
                    f" (resuming: {len(resume.completed)} chapter(s) done)"
                    if resume.previous
                    else ""
                )
                + (f", {len(carried)} glossary terms carried over" if carried else "")
                + (f", {len(known)} compendium entries carried over" if known else ""),
                "data": {"resumed_chapters": sorted(resume.completed)},
            },
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
                # sent only after the DB update below: a client closing on it must see it saved
                final_message = _client_message(event)
            else:
                publish(book_id, _client_message(event))

        if pipeline._cancelled and final_message is None:
            status = BookStatus.paused
            final_message = {"event": "cancelled", "message": "Translation paused, progress saved"}
    except Exception as e:
        error = str(e)
        publish(book_id, {"event": "error", "message": f"Translation failed: {e}"})
    finally:
        active_jobs.pop(book_id, None)
        run_started.pop(book_id, None)
        await store.finish(status, output_path, error)
        if final_message:
            publish(book_id, final_message)
        publish(book_id, FINAL)
    return status
