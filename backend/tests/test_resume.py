import pytest
from sqlalchemy import select

from app.agents.pipeline import TranslationPipeline
from app.db.database import async_session
from app.db.models import Book, BookStatus, Chapter, ChapterStatus, GlossaryEntry
from app.knowledge.store import CompendiumStore, GlossaryStore
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
    store = JobStore(book_id)
    resume = await store.prepare(doc.units, restart=restart)
    glossaries, compendiums = await stores(book_id)
    pipeline = TranslationPipeline(
        llm=llm,
        chunker=small_chunks(),
        enable_review=False,
        glossaries=glossaries,
        compendiums=compendiums,
    )
    if stop_after:
        default = llm._build_result

        def handler(prompt, n):
            if n >= stop_after:
                pipeline.cancel()
            return default(TranslationResult, [_human(prompt)])

        llm.handlers[TranslationResult] = handler

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


async def stores(book_id):
    """The book's live glossary and compendium stores, loaded from the database."""
    glossaries = GlossaryStore(f"book:{book_id}", {book_id})
    compendiums = CompendiumStore(f"book:{book_id}", {book_id})
    await glossaries.load()
    await glossaries.join(book_id)  # learned terms are written to the book
    await compendiums.load()
    await compendiums.join(book_id)
    return glossaries, compendiums


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
    glossaries, _ = await stores(book_id)
    assert [g.source_term for g in glossaries.glossary.entries] == ["Mara"]


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


@pytest.mark.parametrize("analysis", [None, {"summary": "s"}])  # pause in analysis / in units
async def test_pause_does_not_wait_for_slow_model_calls(sample_epub, tmp_path, analysis):
    import asyncio
    import time

    pipeline = TranslationPipeline(llm=ScriptedLLM(delay=30), enable_review=False)
    doc = open_document(sample_epub)

    async def pause_soon():
        await asyncio.sleep(0.3)
        pipeline.cancel()

    pauser = asyncio.create_task(pause_soon())
    started = time.monotonic()
    events = [
        e async for e in translate_document(doc, pipeline, tmp_path / "o.epub", analysis=analysis)
    ]
    await pauser
    assert time.monotonic() - started < 3
    assert not any(e.event_type == "job_complete" for e in events)


async def test_loading_drops_learned_near_duplicates_but_keeps_user_terms(book_id, sample_epub):
    async with async_session() as s:
        for term, user in [("Mara's", False), ("Mara", True), ("the Lighthouse", False),
                           ("Lighthouse", False), ("lighthouse keeper", True)]:  # fmt: skip
            s.add(GlossaryEntry(book_id=book_id, source_term=term, target_term=term,
                                user_edited=user))  # fmt: skip
        await s.commit()
    glossaries, _ = await stores(book_id)
    assert [g.source_term for g in glossaries.glossary.entries] == [
        "Mara",
        "lighthouse keeper",
        "the Lighthouse",
    ]
    async with async_session() as s:
        rows = (await s.execute(select(GlossaryEntry.source_term))).scalars().all()
    assert sorted(rows) == ["Mara", "lighthouse keeper", "the Lighthouse"]


async def test_compendium_is_persisted_reloaded_and_reset_on_restart(book_id, sample_epub):
    from app.db.models import CompendiumRecord
    from app.models.schemas import CompendiumEntry

    llm = ScriptedLLM()
    default = llm._build_result

    def handler(prompt, n):
        result = default(TranslationResult, [_human(prompt)])
        result.compendium_updates = [CompendiumEntry(name="Mara", gender="female")]
        return result

    llm.handlers[TranslationResult] = handler
    await run_job(book_id, sample_epub, llm, concurrency=1)
    async with async_session() as s:
        s.add(CompendiumRecord(book_id=book_id, name="Old Tom", user_edited=True))
        await s.commit()

    _, compendiums = await stores(book_id)
    assert [(c.name, c.gender) for c in compendiums.compendium.entries] == [
        ("Old Tom", "unknown"),  # the user's first
        ("Mara", "female"),
    ]

    await JobStore(book_id).prepare(open_document(sample_epub).units, restart=True)
    _, compendiums = await stores(book_id)
    assert [c.name for c in compendiums.compendium.entries] == ["Old Tom"]
