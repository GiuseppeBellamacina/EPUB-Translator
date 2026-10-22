"""
Job Store — persists translation progress so any interrupted job can resume.

Every checkpoint event is written as soon as it arrives (one short session per
event, events are handled sequentially by the single job consumer):

- ``analysis_complete`` → ``Book.analysis`` + glossary
- ``glossary_update``   → new glossary entries
- ``chunk_done``        → ``Chapter.block_translations`` slice
- ``chapter_saved``     → full block translations, translated HTML, chapter status
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select, update

from app.agents.pipeline import TranslationProgress
from app.db.database import async_session
from app.db.models import (
    Book,
    BookStatus,
    Chapter,
    ChapterStatus,
    GlossaryEntry,
    TranslationJob,
)
from app.models.schemas import GlossaryItem
from app.services.documents import Translations, Unit


@dataclass
class ResumeState:
    previous: Translations = field(default_factory=dict)
    completed: set[int] = field(default_factory=set)
    analysis: dict | None = None
    glossary: list[GlossaryItem] = field(default_factory=list)


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

        ``restart`` discards all progress and auto-generated glossary entries
        (user-edited entries are kept).
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
                for entry in await self._glossary_rows(db):
                    if not entry.user_edited:
                        await db.delete(entry)
            await db.commit()

            state = ResumeState(analysis=book.analysis)
            for i, chapter in chapters.items():
                if chapter.block_translations is not None:
                    state.previous[i] = chapter.block_translations
                    if chapter.status == ChapterStatus.completed:
                        state.completed.add(i)
            state.glossary = [
                GlossaryItem(
                    source_term=e.source_term,
                    target_term=e.target_term,
                    context=e.context,
                    do_not_translate=e.do_not_translate,
                )
                for e in await self._glossary_rows(db)
            ]
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
                    await self._save_glossary(db, event.data.get("glossary", []))
                    await db.commit()
            case "glossary_update":
                async with async_session() as db:
                    await self._save_glossary(db, event.data["new_terms"])
                    await db.commit()
            case "chunk_done":
                await self._save_chunk(event)
            case "chapter_saved":
                await self._save_chapter(event)

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

    async def _glossary_rows(self, db) -> list[GlossaryEntry]:
        result = await db.execute(
            select(GlossaryEntry).where(GlossaryEntry.book_id == self.book_id)
        )
        return list(result.scalars().all())

    async def _save_glossary(self, db, entries: list[dict]) -> None:
        existing = {e.source_term.lower() for e in await self._glossary_rows(db)}
        for entry in entries:
            if entry["source_term"].lower() in existing:
                continue
            existing.add(entry["source_term"].lower())
            db.add(
                GlossaryEntry(
                    book_id=self.book_id,
                    source_term=entry["source_term"],
                    target_term=entry["target_term"],
                    context=entry.get("context"),
                    do_not_translate=entry.get("do_not_translate", False),
                )
            )

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
