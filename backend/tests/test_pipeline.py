import ebooklib

from app.agents.pipeline import TranslationPipeline
from app.models.schemas import ReviewResult, TranslationResult
from app.services.epub_service import EpubService
from app.services.html_processor import extract_visible_text


async def _run(pipeline, book):
    return [e async for e in EpubService.translate_book(book, pipeline)]


async def test_translate_book_end_to_end(llm, sample_epub):
    book = EpubService.load_book(sample_epub)
    events = await _run(TranslationPipeline(llm=llm), book)

    done = events[-1]
    assert done.event_type == "job_complete"
    out = EpubService.load_book(done.data["output_path"])
    texts = [
        extract_visible_text(i.get_content())
        for i in out.get_items()
        if i.get_type() == ebooklib.ITEM_DOCUMENT and "chapter" in i.get_name()
    ]
    assert len(texts) == 3
    assert all("BAU" in t and "MIAO" in t for t in texts)


async def test_rejected_review_triggers_one_retry(llm, sample_epub):
    llm.handlers[ReviewResult] = lambda text, n: ReviewResult(approved=n > 1, issues=["bad"])
    book = EpubService.load_book(sample_epub)
    await _run(TranslationPipeline(llm=llm, max_retries=1), book)
    # First chunk is translated twice (rejected once), every other chunk once.
    chunks = sum(1 for _ in llm.calls_for(ReviewResult))
    assert len(llm.calls_for(TranslationResult)) == chunks
