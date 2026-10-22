import pytest
from sqlalchemy import select

from app.agents.pipeline import TranslationPipeline
from app.db.database import async_session
from app.db.models import Book, BookStatus, Chapter, ChapterStatus, GlossaryEntry
from app.models.schemas import GlossaryItem, TranslationResult
from app.services.chunker import SmartChunker
from app.services.documents import open_document
from app.services.job_store import JobStore, recover_interrupted_jobs
from app.services.translation_service import translate_document
from tests.conftest import ScriptedLLM


def small_chunks() -> SmartChunker:
    return SmartChunker(target_tokens=10, max_tokens=20, overlap_blocks=1)  # ~1 block per chunk


@pytest.fixture
async def book_id(db, sample_epub):
    async with async_session() as s:
        book = Book(filename="sample.epub", original_path=str(sample_epub))
        s.add(book)
        await s.commit()
        return book.id


async def run_job(book_id, path, llm, restart=False, stop_after=None, concurrency=2):
    """Translate like the WebSocket handler does, optionally pausing after N translations."""
    doc = open_document(path)
    pipeline = TranslationPipeline(llm=llm, chunker=small_chunks(), enable_review=False)
    if stop_after:
        default = llm._build_result

        def handler(prompt, n):
            if n >= stop_after:
                pipeline.cancel()
            return default(TranslationResult, [_human(prompt)])

        llm.handlers[TranslationResult] = handler

    store = JobStore(book_id)
    resume = await store.prepare(doc.units, restart=restart)
    pipeline.set_glossary(resume.glossary)
    events = []
    async for event in translate_document(
        doc,
        pipeline,
        path.with_name("out.epub"),
        previous=resume.previous,
        completed=resume.completed,
        analysis=resume.analysis,
        max_concurrency=concurrency,
    ):
        await store.handle(event)
        events.append(event)
    return events


def chunk_counts(path, previous: dict) -> tuple[int, int]:
    """(total chunks, chunks with untranslated blocks) for a checkpoint."""
    doc, chunker = open_document(path), small_chunks()
    total = todo = 0
    for i in range(len(doc.units)):
        prev, offset = previous.get(i), 0
        for chunk in chunker.create_chunks(doc.blocks(i, chunker)):
            n = len(chunk.blocks)
            total += 1
            todo += prev is None or None in prev[offset : offset + n]
            offset += n
    return total, todo


def _human(text):
    from langchain_core.messages import HumanMessage

    return HumanMessage(content=text)


async def chapters(book_id) -> list[Chapter]:
    async with async_session() as s:
        result = await s.execute(
            select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.order_index)
        )
        return list(result.scalars())


async def test_interrupted_job_resumes_without_retranslating(book_id, sample_epub):
    first = ScriptedLLM()
    events = await run_job(book_id, sample_epub, first, stop_after=5)
    assert events[-1].event_type != "job_complete"

    total, todo = chunk_counts(
        sample_epub, {c.order_index: c.block_translations for c in await chapters(book_id)}
    )
    # Every translation that completed before the stop was checkpointed
    assert total - todo == 4  # calls 1-4 finished; the 5th triggered the stop

    second = ScriptedLLM()
    events = await run_job(book_id, sample_epub, second)
    assert events[-1].event_type == "job_complete"
    assert events[-1].data["failed_units"] == []
    # Only the missing chunks were translated, analysis not repeated.
    assert len(second.calls_for(TranslationResult)) == todo
    assert not any(e.event_type == "analysis_complete" for e in events)

    rows = await chapters(book_id)
    assert all(c.status == ChapterStatus.completed for c in rows)
    out = open_document(events[-1].data["output_path"])
    for i, unit in enumerate(out.units):
        if "chapter" in unit.title:
            assert "BAU" in out.text(i) and "Mara" in out.text(i) or "letter" in out.text(i).lower()


async def test_completed_chapters_are_skipped(book_id, sample_epub):
    await run_job(book_id, sample_epub, ScriptedLLM())
    again = ScriptedLLM()
    events = await run_job(book_id, sample_epub, again)
    assert again.calls_for(TranslationResult) == []
    assert sum(e.event_type == "chapter_skipped" for e in events) == 4  # 3 chapters + nav
    assert events[-1].event_type == "job_complete"


async def test_restart_discards_progress_but_keeps_user_glossary(book_id, sample_epub):
    await run_job(book_id, sample_epub, ScriptedLLM())
    async with async_session() as s:
        s.add(
            GlossaryEntry(book_id=book_id, source_term="Mara", target_term="Mara", user_edited=True)
        )
        s.add(GlossaryEntry(book_id=book_id, source_term="storm", target_term="tempesta"))
        await s.commit()

    again = ScriptedLLM()
    await run_job(book_id, sample_epub, again, restart=True)
    assert len(again.calls_for(TranslationResult)) == chunk_counts(sample_epub, {})[0]
    async with async_session() as s:
        terms = {e.source_term for e in (await s.execute(select(GlossaryEntry))).scalars()}
    assert "Mara" in terms and "storm" not in terms


async def test_learned_glossary_is_persisted_and_reloaded(book_id, sample_epub):
    llm = ScriptedLLM()
    llm.handlers[TranslationResult] = lambda prompt, n: TranslationResult(
        translated_text="ok",
        new_terms=[GlossaryItem(source_term="Mara", target_term="Mara", do_not_translate=True)],
    )
    await run_job(book_id, sample_epub, llm, concurrency=1)
    resume = await JobStore(book_id).prepare(open_document(sample_epub).units)
    assert [g.source_term for g in resume.glossary] == ["Mara"]


@pytest.mark.parametrize("limit", [1, 2])
async def test_chapter_concurrency_is_bounded(book_id, sample_epub, limit):
    llm = ScriptedLLM(delay=0.02)
    await run_job(book_id, sample_epub, llm, concurrency=limit)
    assert llm.peak == limit


async def test_startup_recovery_pauses_orphaned_jobs(book_id):
    async with async_session() as s:
        book = await s.get(Book, book_id)
        book.status = BookStatus.translating
        await s.commit()
    await recover_interrupted_jobs()
    async with async_session() as s:
        assert (await s.get(Book, book_id)).status == BookStatus.paused
