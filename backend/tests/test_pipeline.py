from app.agents.pipeline import TranslationPipeline
from app.models.schemas import ReviewIssue, ReviewResult, TranslationResult
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
    # the chunk call fails, then its first block too: the chunk cannot be translated
    llm.fail[TranslationResult] = [RuntimeError("boom")] * 2
    events = await translate(sample_epub, TranslationPipeline(llm=llm, enable_review=False))

    done = [e for e in events if e.event_type == "chapter_done" and e.data["translated_blocks"]]
    failed = [e for e in done if e.data["failed_chunks"]]
    assert len(failed) == 1 and failed[0].data["failed_chunks"] == [0]
    assert all(t is None for t in failed[0].data["translated_blocks"])
    assert all(t is not None for e in done if e not in failed for t in e.data["translated_blocks"])
    assert events[-1].data["failed_units"] == [failed[0].chapter_index]


async def test_rejected_review_triggers_one_retry(llm, sample_epub):
    llm.handlers[ReviewResult] = lambda text, n: ReviewResult(
        issues=[ReviewIssue(severity="major", description="bad")] if n == 1 else []
    )
    await translate(sample_epub, TranslationPipeline(llm=llm, max_retries=1))
    # First chunk is translated twice (rejected once), every other chunk once.
    assert len(llm.calls_for(TranslationResult)) == len(llm.calls_for(ReviewResult))


async def test_failed_chunk_call_falls_back_to_blocks_without_repeating_it(llm, monkeypatch):
    from app.agents.translator_agent import translate_blocks

    monkeypatch.setattr("app.core.config.settings.chain_retries", 3)
    llm.fail[TranslationResult] = [RuntimeError("length limit reached")]
    kwargs = dict(
        context="", chapter_summary="", glossary=[], source_language="en", target_language="it"
    )
    out, *_ = await translate_blocks(llm, ["One.", "Two."], following="Three.", **kwargs)
    assert out == ["BAU One. MIAO", "BAU Two. MIAO"]
    calls = llm.calls_for(TranslationResult)
    assert len(calls) == 3  # one failed chunk call (no identical retries) + two blocks
    assert "FOLLOWING TEXT (comes right after, do NOT translate this):\nTwo." in calls[1]
    assert "do NOT translate this):\nThree." in calls[2]


async def test_last_chunk_sees_the_start_of_the_next_unit(llm, sample_epub):
    await translate(sample_epub, TranslationPipeline(llm=llm, enable_review=False))
    prompts = llm.calls_for(TranslationResult)
    chapter_one = next(p for p in prompts if "The old lighthouse" in p.split("---")[1])
    following = chapter_one.split("FOLLOWING TEXT")[1].split("---")[0]
    assert "Chapter 2: The Letter" in following


def test_keep_unfinished_drops_only_an_added_closing_quote():
    from app.agents.translator_agent import keep_unfinished

    cut = "“Well, Kirito…Why do they want to kill"
    assert keep_unfinished(cut, "“Beh, Kirito… Perché vogliono uccidere”") == (
        "“Beh, Kirito… Perché vogliono uccidere"
    )
    assert keep_unfinished("“Done.”", "“Fatto.”") == "“Fatto.”"
    assert keep_unfinished(cut, "“Beh… perché uccidere") == "“Beh… perché uccidere"


async def test_minor_issues_do_not_trigger_a_retranslation(llm, sample_epub):
    llm.handlers[ReviewResult] = lambda text, n: ReviewResult(
        issues=[ReviewIssue(severity="minor", description="'sbigottite' is a bit literal")],
        corrected_text="not used",
    )
    await translate(sample_epub, TranslationPipeline(llm=llm))
    assert len(llm.calls_for(TranslationResult)) == len(llm.calls_for(ReviewResult))
    assert ReviewResult(issues=[ReviewIssue(severity="minor", description="x")]).approved
    assert not ReviewResult(glossary_violations=["Mara"]).approved


async def test_review_can_use_a_different_model(sample_epub):
    from tests.conftest import ScriptedLLM

    translator, reviewer = ScriptedLLM(), ScriptedLLM()
    await translate(sample_epub, TranslationPipeline(llm=translator, review_llm=reviewer))
    assert translator.calls_for(ReviewResult) == []
    assert len(reviewer.calls_for(ReviewResult)) == len(translator.calls_for(TranslationResult))


def test_do_not_translate_terms_are_shown_as_themselves():
    from app.agents.translator_agent import _format_glossary
    from app.models.schemas import GlossaryItem

    text = _format_glossary(
        [GlossaryItem(source_term="Kirito", target_term="Kirito", do_not_translate=True)]
    )
    assert text == "- Kirito → Kirito (keep exactly as written)"
    assert "[" not in text  # no marker the model could copy into the translation
