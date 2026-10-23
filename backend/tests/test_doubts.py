import pymupdf
from sqlalchemy import select

from app.agents.pipeline import TranslationPipeline
from app.core.fake_llm import _extract_source_text, meow_transform
from app.db.database import async_session
from app.db.models import Bookmark, Chapter
from app.models.schemas import CompendiumEntry, Doubt, DoubtResolution, TranslationResult
from app.services.documents import open_document
from tests.conftest import translate
from tests.test_resume import book_id, run_job  # noqa: F401 (fixture)


def doubt_on_first_call(prompt, n):
    source = _extract_source_text(prompt)
    first_words = " ".join(source.split()[:3])
    doubts = [Doubt(quote=first_words, reason="who is 'she'?")] if n == 1 else []
    return TranslationResult(translated_text=meow_transform(source), doubts=doubts)


def fix(prompt, n):
    current = prompt.split("TRANSLATION (")[1].split("\n", 1)[1].split("\n\nDOUBTS")[0]
    return DoubtResolution(translation="FIXED " + current, note="She is Mara.")


async def test_a_doubt_is_reviewed_at_the_end_and_its_fix_saved(llm, sample_epub):
    llm.handlers[TranslationResult] = doubt_on_first_call
    llm.handlers[DoubtResolution] = fix
    events = await translate(sample_epub, TranslationPipeline(llm=llm, enable_review=False))

    [flagged] = [e for e in events if e.event_type == "doubt_flagged"]
    [resolved] = [e for e in events if e.event_type == "doubt_resolved"]
    assert "who is 'she'?" in llm.calls_for(DoubtResolution)[0]
    assert resolved.data["status"] == "fixed" and resolved.chapter_index == flagged.chapter_index
    block = flagged.data["doubts"][0]["block"]
    last_save = [e for e in events if e.event_type == "chapter_saved"][-1]
    assert last_save.data["translations"][block].startswith("FIXED BAU")
    assert events[-1].event_type == "job_complete"


async def test_the_doubt_review_can_be_turned_off(llm, sample_epub):
    llm.handlers[TranslationResult] = doubt_on_first_call
    pipeline = TranslationPipeline(llm=llm, enable_review=False, doubt_review=False)
    events = await translate(sample_epub, pipeline)
    assert [e for e in events if e.event_type == "doubt_flagged"]
    assert llm.calls_for(DoubtResolution) == []
    assert events[-1].event_type == "job_complete"


async def test_a_corrected_gender_bookmarks_the_passages_already_translated(llm, sample_epub):
    def handler(prompt, n):
        source = _extract_source_text(prompt)
        if "Mara lit the lamp" in source:
            found = [CompendiumEntry(name="Mara", gender="female", evidence="Mara lit the lamp")]
        else:
            found = [CompendiumEntry(name="Mara", gender="male")] if "Mara" in source else []
        return TranslationResult(translated_text=meow_transform(source), compendium_updates=found)

    llm.handlers[TranslationResult] = handler
    events = await translate(sample_epub, TranslationPipeline(llm=llm, enable_review=False))

    [update] = [e for e in events if e.event_type == "compendium_update" and e.data["corrected"]]
    auto = [e for e in events if e.event_type == "doubt_flagged"]
    reasons = {d["reason"] for e in auto for d in e.data["doubts"]}
    assert update.data["corrected"] == ["Mara"]
    assert reasons == {"Compendium corrected: Mara is female"}
    assert len({e.chapter_index for e in auto}) >= 2  # the earlier chapters naming her
    assert len(llm.calls_for(DoubtResolution)) == sum(len(e.data["doubts"]) for e in auto)


async def test_a_doubt_in_a_page_group_lands_on_its_page(llm, tmp_path):
    doc = pymupdf.open()
    for line in ["The keeper climbed the stairs", "and lit the lamp before", "the storm came."]:
        doc.new_page().insert_htmlbox(pymupdf.Rect(72, 72, 520, 140), f"<p>{line}</p>")
    path = tmp_path / "pages.pdf"
    doc.save(path)

    llm.handlers[TranslationResult] = lambda prompt, n: TranslationResult(
        translated_text=meow_transform(_extract_source_text(prompt)),
        doubts=[Doubt(quote="lit the lamp", reason="which lamp?")],
    )
    events = await translate(path, TranslationPipeline(llm=llm, enable_review=False))
    [flagged] = [e for e in events if e.event_type == "doubt_flagged"]
    assert (flagged.chapter_index, flagged.data["doubts"][0]["block"]) == (1, 0)


async def test_an_unresolved_doubt_stays_open_and_is_reviewed_on_resume(
    llm, sample_epub, book_id, monkeypatch  # noqa: F811
):
    monkeypatch.setattr("app.core.config.settings.chain_retries", 1)
    llm.handlers[TranslationResult] = doubt_on_first_call
    llm.handlers[DoubtResolution] = fix
    llm.fail[DoubtResolution] = [RuntimeError("model down")]
    first = await run_job(book_id, sample_epub, llm)
    assert any("Doubt review failed" in (e.message or "") for e in first)

    async def bookmarks():
        async with async_session() as db:
            return list((await db.execute(select(Bookmark))).scalars())

    [open_one] = await bookmarks()
    assert open_one.status == "open"

    await run_job(book_id, sample_epub, llm)  # every unit done: only the review runs
    [closed] = await bookmarks()
    assert closed.status == "fixed" and closed.resolution.startswith("FIXED")
    async with async_session() as db:
        chapter = await db.scalar(select(Chapter).where(Chapter.order_index == closed.unit))
    assert chapter.block_translations[closed.block] == closed.resolution


async def test_a_glossary_change_is_replaced_as_is_and_the_rest_goes_to_the_model(llm, sample_epub):
    events = await translate(sample_epub, TranslationPipeline(llm=llm, enable_review=False))
    previous = {
        e.chapter_index: e.data["translations"] for e in events if e.event_type == "chapter_saved"
    }
    unit = next(u for u, t in previous.items() if any("lighthouse" in x for x in t))
    exact = next(b for b, x in enumerate(previous[unit]) if "lighthouse" in x)
    other = next(b for b, x in enumerate(previous[unit]) if "lighthouse" not in x.lower())
    change = {"quote": "lighthouse", "reason": "Glossary: lighthouse → torre", "new_text": "torre"}
    bookmarks = [
        {"unit": unit, "block": exact, "old_text": "lighthouse", **change},
        {"unit": unit, "block": other, "old_text": "lighthouse", **change},  # not there as is
    ]
    llm.handlers[DoubtResolution] = fix
    again = await translate(
        sample_epub,
        TranslationPipeline(llm=llm, enable_review=False),
        previous=previous,
        completed=set(previous),
        analysis={"summary": ""},
        bookmarks=bookmarks,
    )
    resolved = {e.data["block"]: e.data for e in again if e.event_type == "doubt_resolved"}
    assert resolved[exact]["note"] == "Replaced lighthouse → torre"
    assert (
        "torre" in resolved[exact]["translation"]
        and "lighthouse" not in resolved[exact]["translation"]
    )
    assert len(llm.calls_for(DoubtResolution)) == 1  # only the block without an exact match
    out = open_document(again[-1].data["output_path"])
    assert "torre" in out.text(unit)


async def test_bookmarks_added_during_the_review_are_reviewed_in_the_same_run(llm, sample_epub):
    llm.handlers[TranslationResult] = doubt_on_first_call
    pipeline = TranslationPipeline(llm=llm, enable_review=False)

    def late_edit(prompt, n):
        if n == 1:  # an edit in the UI while the review runs
            pipeline.added_bookmarks.append(
                {"unit": 1, "block": 0, "quote": "Mara", "reason": "Mara: gender male → female"}
            )
        return fix(prompt, n)

    llm.handlers[DoubtResolution] = late_edit
    events = await translate(sample_epub, pipeline)
    assert len(llm.calls_for(DoubtResolution)) == 2
    assert "Mara: gender male → female" in llm.calls_for(DoubtResolution)[1]
    assert events[-1].event_type == "job_complete"
