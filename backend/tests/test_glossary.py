from app.agents.glossary import Glossary
from app.agents.pipeline import TranslationPipeline
from app.core.fake_llm import _extract_source_text, meow_transform
from app.models.schemas import GlossaryItem, ReviewIssue, ReviewResult, TranslationResult
from tests.conftest import translate


def item(source, target="", dnt=False):
    return GlossaryItem(source_term=source, target_term=target or source, do_not_translate=dnt)


def test_add_rejects_hallucinated_duplicate_and_empty_terms():
    g = Glossary([item("Mara", dnt=True)])
    accepted = g.add(
        [
            item("mara", "Maria"),  # duplicate (case-insensitive): never overrides
            item("lighthouse", "faro"),  # in source
            item("dragon", "drago"),  # not in source: hallucinated
            item("x", "y"),  # too short
            GlossaryItem(source_term="storm", target_term=" "),  # no target
        ],
        source_text="The <1>lighthouse</1> keeper Mara watched the storm.",
    )
    assert [e.source_term for e in accepted] == ["lighthouse"]
    assert g.entries[0].do_not_translate


def test_relevant_selects_terms_present_in_text():
    g = Glossary([item("Mara", dnt=True), item("lighthouse", "faro"), item("letter", "lettera")])
    assert [e.source_term for e in g.relevant("Mara climbed the lighthouse.")] == [
        "Mara",
        "lighthouse",
    ]


def test_enforce_replaces_untranslated_terms_with_case_and_skips_unsafe_ones():
    g = Glossary(
        [
            item("lighthouse", "faro"),
            item("Mara", dnt=True),
            item("ok", "va bene"),  # too short to enforce
            item("radio", "radio"),  # identical in both languages
        ]
    )
    text = "Il LIGHTHOUSE, il Lighthouse e il lighthouse; Mara ok radio."
    assert g.enforce(text) == "Il FARO, il Faro e il faro; Mara ok radio."


async def test_terms_learned_in_one_chapter_reach_the_next(llm, sample_epub):
    # Chapter 1 proposes "Mara"; later prompts must list it in the glossary.
    def handler(prompt, n):
        source = _extract_source_text(prompt)
        terms = [item("Mara", dnt=True)] if "Mara" in source and n == 1 else []
        return TranslationResult(translated_text=meow_transform(source), new_terms=terms)

    llm.handlers[TranslationResult] = handler
    pipeline = TranslationPipeline(llm=llm, enable_review=False)
    events = [e for e in await translate(sample_epub, pipeline)]

    assert [
        e.data["new_terms"][0]["source_term"] for e in events if e.event_type == "glossary_update"
    ] == ["Mara"]
    later_prompts = [t for t in llm.calls_for(TranslationResult)[1:] if "Mara" in t.split("---")[1]]
    assert later_prompts and all(
        "- Mara → Mara (keep exactly as written)" in t for t in later_prompts
    )


async def test_rejection_feedback_reaches_the_retranslation(llm, sample_epub):
    llm.handlers[ReviewResult] = lambda text, n: ReviewResult(
        issues=[ReviewIssue(severity="major", description="Wrong tense")] if n == 1 else [],
        glossary_violations=["Mara"] if n == 1 else [],
    )
    pipeline = TranslationPipeline(llm=llm, max_retries=1)
    await translate(sample_epub, pipeline)

    first, retry = llm.calls_for(TranslationResult)[:2]
    assert "REVIEWER REJECTED" not in first
    assert "- Wrong tense" in retry and "- Glossary violation: Mara" in retry


async def test_review_can_be_disabled(llm, sample_epub):
    pipeline = TranslationPipeline(llm=llm, enable_review=False)
    await translate(sample_epub, pipeline)
    assert llm.calls_for(ReviewResult) == []
