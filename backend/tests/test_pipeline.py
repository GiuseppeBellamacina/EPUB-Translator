from app.agents.pipeline import TranslationPipeline
from app.models.schemas import ReviewResult, TranslationResult
from app.services.documents import open_document
from tests.conftest import translate


async def test_translate_book_end_to_end(llm, sample_epub):
    events = await translate(sample_epub, TranslationPipeline(llm=llm))

    done = events[-1]
    assert done.event_type == "job_complete" and done.data["failed_units"] == []
    out = open_document(done.data["output_path"])
    texts = [out.text(i) for i, u in enumerate(out.units) if "chapter" in u.title]
    assert len(texts) == 3
    assert all("BAU" in t and "MIAO" in t for t in texts)


async def test_failed_chunk_is_not_stored_as_translated(llm, sample_epub, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.chain_retries", 1)
    llm.fail[TranslationResult] = [RuntimeError("boom")]  # first chunk translated
    events = await translate(sample_epub, TranslationPipeline(llm=llm, enable_review=False))

    done = [e for e in events if e.event_type == "chapter_done" and e.data["translated_blocks"]]
    failed = [e for e in done if e.data["failed_chunks"]]
    assert len(failed) == 1 and failed[0].data["failed_chunks"] == [0]
    assert all(t is None for t in failed[0].data["translated_blocks"])
    assert all(t is not None for e in done if e not in failed for t in e.data["translated_blocks"])
    assert events[-1].data["failed_units"] == [failed[0].chapter_index]


async def test_rejected_review_triggers_one_retry(llm, sample_epub):
    llm.handlers[ReviewResult] = lambda text, n: ReviewResult(approved=n > 1, issues=["bad"])
    await translate(sample_epub, TranslationPipeline(llm=llm, max_retries=1))
    # First chunk is translated twice (rejected once), every other chunk once.
    assert len(llm.calls_for(TranslationResult)) == len(llm.calls_for(ReviewResult))
