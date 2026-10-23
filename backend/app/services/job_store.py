"""
Job Store — persists translation progress so any interrupted job can resume.

Every checkpoint event is written as soon as it arrives (one short session per
event, events are handled sequentially by the single job consumer):

- ``analysis_complete`` → ``Book.analysis``
- ``chunk_done``        → ``Chapter.block_translations`` slice
- ``chapter_saved``     → full block translations, translated HTML, chapter status
- ``doubt_flagged``     → ``Bookmark`` rows (open); ``doubt_resolved`` closes them

Glossary and compendium are persisted by their live stores (``app/knowledge/store``).
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, func, select, update

from app.agents.pipeline import TranslationProgress
from app.db.database import async_session
from app.db.models import (
    Book,
    Bookmark,
    BookStatus,
    Chapter,
    ChapterStatus,
    CompendiumRecord,
    GlossaryEntry,
    TranslationJob,
)
from app.services.documents import Translations, Unit


@dataclass
class ResumeState:
    previous: Translations = field(default_factory=dict)
    completed: set[int] = field(default_factory=set)
    analysis: dict | None = None
    bookmarks: list[dict] = field(default_factory=list)  # open doubts, for the final review


async def recover_interrupted_jobs() -> None:
    """On startup, jobs left ``translating`` by a crash/restart become ``paused``."""
    async with async_session() as db:
        await db.execute(
            update(Book)
            .where(Book.status == BookStatus.translating)
            .values(status=BookStatus.paused)
        )
        await db.execute(
            update(TranslationJob)
            .where(TranslationJob.status == "running")
            .values(status="interrupted", completed_at=datetime.utcnow())
        )
        await db.commit()


class JobStore:
    def __init__(self, book_id: int):
        self.book_id = book_id
        self.job_id: int | None = None

    async def prepare(self, units: list[Unit], restart: bool = False) -> ResumeState:
        """Ensure a Chapter row per unit and load the resume checkpoint.

        ``restart`` discards all progress and the learned glossary and compendium
        entries of the book (user-edited entries are kept).
        """
        async with async_session() as db:
            book = await db.get(Book, self.book_id)
            chapters = {c.order_index: c for c in await self._chapters(db)}
            for i, unit in enumerate(units):
                if i not in chapters:
                    chapters[i] = Chapter(
                        book_id=self.book_id, item_id=unit.item_id, title=unit.title, order_index=i
                    )
                    db.add(chapters[i])

            if restart:
                for chapter in chapters.values():
                    chapter.block_translations = None
                    chapter.translated_html = None
                    chapter.status = ChapterStatus.pending
                book.analysis = None
                book.translated_chapters = 0
                book.translated_path = None
                await db.execute(delete(Bookmark).where(Bookmark.book_id == self.book_id))
                for model in (GlossaryEntry, CompendiumRecord):
                    await db.execute(
                        delete(model).where(
                            model.book_id == self.book_id, model.user_edited.is_not(True)
                        )
                    )
            await db.commit()

            state = ResumeState(analysis=book.analysis)
            rows = await db.execute(
                select(Bookmark).where(Bookmark.book_id == self.book_id, Bookmark.status == "open")
            )
            state.bookmarks = [
                {"unit": b.unit, "block": b.block, "quote": b.quote, "reason": b.reason}
                for b in rows.scalars()
            ]
            for i, chapter in chapters.items():
                if chapter.block_translations is not None:
                    state.previous[i] = chapter.block_translations
                    if chapter.status == ChapterStatus.completed:
                        state.completed.add(i)
            return state

    async def start(self, provider: str, model: str, params: dict) -> None:
        async with async_session() as db:
            book = await db.get(Book, self.book_id)
            book.status = BookStatus.translating
            job = TranslationJob(
                book_id=self.book_id,
                provider=provider,
                model=model,
                params=params,
                status="running",
            )
            db.add(job)
            await db.commit()
            self.job_id = job.id

    async def handle(self, event: TranslationProgress) -> None:
        match event.event_type:
            case "analysis_complete":
                async with async_session() as db:
                    book = await db.get(Book, self.book_id)
                    book.analysis = event.data["analysis"]
                    await db.commit()
            case "chunk_done":
                await self._save_chunk(event)
            case "chapter_saved":
                await self._save_chapter(event)
            case "doubt_flagged":
                await self._save_doubts(event)
            case "doubt_resolved":
                await self._resolve_doubt(event)

    async def finish(self, status: BookStatus, output_path: str | None, error: str | None) -> None:
        async with async_session() as db:
            book = await db.get(Book, self.book_id)
            book.status = status
            if output_path:
                book.translated_path = output_path
            if self.job_id:
                job = await db.get(TranslationJob, self.job_id)
                job.status = status.value
                job.error_message = error
                job.completed_at = datetime.utcnow()
                job.progress = (book.translated_chapters or 0) / max(1, book.total_chapters or 1)
            await db.commit()

    # --- helpers --------------------------------------------------------------

    async def _chapters(self, db) -> list[Chapter]:
        result = await db.execute(select(Chapter).where(Chapter.book_id == self.book_id))
        return list(result.scalars().all())

    async def _chapter(self, db, order_index: int) -> Chapter | None:
        result = await db.execute(
            select(Chapter).where(
                Chapter.book_id == self.book_id, Chapter.order_index == order_index
            )
        )
        return result.scalar_one_or_none()

    async def _save_chunk(self, event: TranslationProgress) -> None:
        data = event.data
        translations = data["translations"]
        if translations is None:  # failed chunk: nothing to checkpoint
            return
        async with async_session() as db:
            chapter = await self._chapter(db, event.chapter_index)
            if chapter is None:
                return
            blocks = list(chapter.block_translations or [])
            if len(blocks) != data["total_blocks"]:
                blocks = [None] * data["total_blocks"]
            blocks[data["offset"] : data["offset"] + len(translations)] = translations
            chapter.block_translations = blocks  # reassign: JSON columns don't track mutation
            chapter.status = ChapterStatus.translating
            await db.commit()

    async def _save_doubts(self, event: TranslationProgress) -> None:
        """New bookmarks; a chunk translated again after a pause flags the same ones."""
        async with async_session() as db:
            rows = await db.execute(
                select(Bookmark.block, Bookmark.quote).where(
                    Bookmark.book_id == self.book_id, Bookmark.unit == event.chapter_index
                )
            )
            known = set(rows.all())
            for doubt in event.data["doubts"]:
                if (doubt["block"], doubt["quote"]) not in known:
                    known.add((doubt["block"], doubt["quote"]))
                    db.add(Bookmark(book_id=self.book_id, unit=event.chapter_index, **doubt))
            await db.commit()

    async def _resolve_doubt(self, event: TranslationProgress) -> None:
        data = event.data
        async with async_session() as db:
            await db.execute(
                update(Bookmark)
                .where(
                    Bookmark.book_id == self.book_id,
                    Bookmark.unit == event.chapter_index,
                    Bookmark.block == data["block"],
                    Bookmark.status == "open",
                )
                .values(status=data["status"], resolution=data["translation"], note=data["note"])
            )
            await db.commit()

    async def _save_chapter(self, event: TranslationProgress) -> None:
        data = event.data
        translations = data["translations"]
        async with async_session() as db:
            chapter = await self._chapter(db, data["order_index"])
            if chapter is None:
                return
            chapter.block_translations = translations
            chapter.translated_html = data.get("translated_html")
            complete = translations is not None and None not in translations
            chapter.status = ChapterStatus.completed if complete else ChapterStatus.failed
            await db.flush()
            book = await db.get(Book, self.book_id)
            book.translated_chapters = await db.scalar(
                select(func.count())
                .select_from(Chapter)
                .where(Chapter.book_id == self.book_id, Chapter.status == ChapterStatus.completed)
            )
            await db.commit()
