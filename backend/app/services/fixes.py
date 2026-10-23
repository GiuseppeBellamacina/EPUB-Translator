"""
Targeted fixes after a glossary or compendium change ("breadcrumbs").

A change made after translating (a term's translation, a character's gender, notes) is
followed back to the passages it touches: the translated blocks whose source names the
term or entry (``translation_service.mention_doubts``). Each becomes a bookmark with the
precise reason, and the doubt review fixes it on its own: a glossary change is replaced
as is where the old translation occurs (no model call), anything else goes to the review
model with just that passage. Nothing else is read again.

A running job takes the bookmarks at its end. A completed book gets a review-only run
(its units are done: only the doubt review runs, then the file is saved), started at once
when the change touches few passages, after a confirmation otherwise.
"""

import asyncio

from pydantic import ValidationError
from sqlalchemy import select

from app.agents.pipeline import TranslationProgress
from app.core.config import settings
from app.db.database import async_session
from app.db.models import Book, BookStatus, Chapter, ProviderConfig, QueueItem, TranslationJob
from app.jobs import RunConfig, jobs
from app.services.chunker import make_chunker
from app.services.documents import open_document
from app.services.job_store import JobStore
from app.services.translation_service import mention_doubts

AUTO_FIX_LIMIT = 50  # passages fixed without asking (one model call each, at most)


async def series_books(book_id: int, keeps) -> set[int]:
    """The book and the books of its series (queues sharing ``keeps``: glossary/compendium)."""
    async with async_session() as db:
        batches = select(QueueItem.batch_id).where(QueueItem.book_id == book_id, keeps.is_(True))
        rows = await db.execute(select(QueueItem.book_id).where(QueueItem.batch_id.in_(batches)))
        return {book_id, *rows.scalars()}


async def bookmark_mentions(book_id: int, names: list[str], **doubt) -> int:
    """Bookmark the book's translated blocks naming any of ``names``; returns how many."""
    async with async_session() as db:
        book = await db.get(Book, book_id)
        rows = await db.execute(
            select(Chapter).where(
                Chapter.book_id == book_id, Chapter.block_translations.is_not(None)
            )
        )
        translated = {c.order_index: c.block_translations for c in rows.scalars()}
    if book is None or not translated:
        return 0
    chunker = make_chunker(settings.chunk_tokens)  # block extraction does not depend on size

    def find() -> dict[int, list[dict]]:
        doc = open_document(book.original_path)
        return mention_doubts(names, translated, lambda i: doc.blocks(i, chunker), **doubt)

    found = await asyncio.to_thread(find)
    store = JobStore(book_id)
    for unit, doubts in found.items():
        event = TranslationProgress("doubt_flagged", chapter_index=unit, data={"doubts": doubts})
        await store.handle(event)
    if pipeline := jobs.runner.active.get(book_id):  # its doubt review takes them at the end
        pipeline.added_bookmarks += [{"unit": u, **d} for u, ds in found.items() for d in ds]
    return sum(len(d) for d in found.values())


async def remember_yes(book_ids: list[int]) -> None:
    """The user confirmed fixes for these books: do not ask again."""
    async with async_session() as db:
        for book_id in book_ids:
            if book := await db.get(Book, book_id):
                book.ask_before_fixes = False
        await db.commit()


async def start_fixes(book_id: int) -> bool:
    """Make the book's open bookmarks be reviewed: a running or queued job does it; a
    completed book gets a review-only run with its last settings. False if it cannot
    (never translated, partly translated: its next run does it, provider gone)."""
    if jobs.is_running(book_id):
        return True
    async with async_session() as db:
        book = await db.get(Book, book_id)
        if book is None or book.status != BookStatus.completed:
            return False
        waiting = await db.scalar(
            select(QueueItem.id).where(
                QueueItem.book_id == book_id,
                QueueItem.status.in_(("pending", "running", "paused")),
            )
        )
        if waiting:
            return True
        job = await db.scalar(
            select(TranslationJob)
            .where(TranslationJob.book_id == book_id, TranslationJob.params.is_not(None))
            .order_by(TranslationJob.id.desc())
        )
        try:
            # never "start over" again, and the review must run whatever the last run chose
            config = RunConfig(
                **{
                    **(job.params if job else {}),
                    "restart": False,
                    "doubt_review": True,
                    "ask_before_fixes": book.ask_before_fixes is not False,  # a "yes" stays
                }
            )
        except ValidationError:
            return False
        if await db.get(ProviderConfig, config.provider_id) is None:
            return False
    await jobs.enqueue([book_id], config, front=True)
    return True


async def follow_change(keeps, book_id: int, names: list[str], auto: bool = True, **doubt) -> dict:
    """Bookmark the passages a change touches in the book and its series, and start their
    fixes when they are few (``auto``) or the books are not to be asked (``ask_before_fixes``
    off). The UI asks before ``start_fixes`` otherwise, once per book."""
    counts = {
        b: await bookmark_mentions(b, names, **doubt) for b in await series_books(book_id, keeps)
    }
    books = sorted(b for b, n in counts.items() if n)
    total = sum(counts.values())
    async with async_session() as db:
        rows = await db.execute(select(Book.ask_before_fixes).where(Book.id.in_(books)))
        ask = any(flag is not False for flag in rows.scalars())
    fixing = total > 0 and (not ask or (auto and total <= AUTO_FIX_LIMIT))
    started = [b for b in books if await start_fixes(b)] if fixing else []
    return {
        "bookmarked": total,
        "fixing": bool(started),
        "confirm": total > 0 and not started,
        "books": books,
    }
