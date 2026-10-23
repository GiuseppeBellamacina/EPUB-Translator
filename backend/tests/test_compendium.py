from app.agents.pipeline import TranslationPipeline
from app.core.fake_llm import _extract_source_text, meow_transform
from app.knowledge.compendium import Compendium, render
from app.models.schemas import CompendiumEntry, ReviewIssue, ReviewResult, TranslationResult
from tests.conftest import translate


def e(name, **kw):
    return CompendiumEntry(name=name, **kw)


def test_merge_matches_names_and_aliases_and_only_fills_what_is_missing():
    c = Compendium()
    c.merge([e("Rudeus Greyrat", aliases=["Rudy"], notes="The narrator.")])
    changed = c.merge([e("Rudy", gender="male", notes="Speaks politely.")])  # alias
    assert [x.name for x in changed] == ["Rudeus Greyrat"]
    rudeus = c.entries[0]
    assert rudeus.gender == "male" and rudeus.notes == "The narrator. Speaks politely."
    # a known gender is not overwritten, a repeated note not added, a variant is the same
    assert c.merge([e("Rudeus Greyrats", gender="female", notes="speaks politely.")]) == []
    assert len(c) == 1 and c.entries[0].gender == "male"

    c.merge([e("Paul", gender="male")], source_text="Zenith smiled.")  # not in the text
    c.merge([e("Paul Greyrat", aliases=["Paul"])], source_text="Paul laughed.")  # alias in it
    assert [x.name for x in c.entries] == ["Rudeus Greyrat", "Paul Greyrat"]
    assert c.entries[1].aliases == ["Paul"]


def test_user_entries_are_never_changed():
    c = Compendium()
    c.merge([e("Sylphiette", gender="female", aliases=["Sylphy"])], user=True)
    assert c.merge([e("Sylphy", gender="male", notes="Elf.", aliases=["Fitz"])]) == []
    assert c.entries == [e("Sylphiette", gender="female", aliases=["Sylphy"])]


def test_a_known_gender_is_corrected_only_with_evidence_from_the_passage():
    c = Compendium()
    c.merge([e("Ghislaine", gender="male")])
    text = "Ghislaine drew her sword; she laughed."
    assert c.merge([e("Ghislaine", gender="female")], source_text=text) == []
    assert c.merge([e("Ghislaine", gender="female", evidence="she cried")], source_text=text) == []
    [fixed] = c.merge([e("Ghislaine", gender="female", evidence="Drew her  sword")], text)
    assert (fixed.gender, fixed.evidence) == ("female", "Drew her  sword")


def test_relevant_and_render():
    c = Compendium()
    c.merge(
        [
            e("Rudeus", gender="male", aliases=["Rudy"], notes="Narrator."),
            e("Roxy", gender="unknown"),
            e("Buena Village", kind="place", gender="n/a"),
        ]
    )
    found = c.relevant("Rudy walked to Buena Village.")
    assert [x.name for x in found] == ["Rudeus", "Buena Village"]
    assert render(c.entries) == (
        "- Rudeus (character, male; also Rudy): Narrator.\n"
        "- Roxy (character, gender unknown)\n"
        "- Buena Village (place)"
    )


async def test_compendium_learned_in_one_chunk_reaches_later_prompts_and_the_reviewer(
    llm, sample_epub
):
    def translate_handler(prompt, n):
        source = _extract_source_text(prompt)
        found = (
            [e("Mara", gender="female", notes="The lighthouse keeper.")] if "Mara" in source else []
        )
        return TranslationResult(translated_text=meow_transform(source), compendium_updates=found)

    llm.handlers[TranslationResult] = translate_handler
    events = await translate(sample_epub, TranslationPipeline(llm=llm))

    updates = [x for x in events if x.event_type == "compendium_update"]
    assert len(updates) == 1 and updates[0].data["entries"][0]["gender"] == "female"
    line = "- Mara (character, female): The lighthouse keeper."
    later = [t for t in llm.calls_for(TranslationResult)[1:] if "Mara" in t.split("---")[1]]
    assert later and all(line in t for t in later)
    reviews = [t for t in llm.calls_for(ReviewResult) if line in t]
    assert reviews  # the reviewer checks genders against the compendium


async def test_a_gender_error_against_the_compendium_is_retranslated(llm, sample_epub):
    calls = []

    def review_handler(prompt, n):
        if "Mara (character, female)" in prompt and not calls:
            calls.append(n)
            issue = ReviewIssue(severity="major", description="'lui' for Mara, who is female")
            return ReviewResult(issues=[issue])
        return ReviewResult()

    llm.handlers[ReviewResult] = review_handler
    pipeline = TranslationPipeline(llm=llm)
    pipeline.set_compendium([e("Mara", gender="female")])
    events = await translate(sample_epub, pipeline)

    rejected = [x for x in events if x.event_type == "chunk_rejected"]
    assert len(rejected) == 1 and "Mara, who is female" in rejected[0].data["issues"][0]
    retry = [t for t in llm.calls_for(TranslationResult) if "Mara, who is female" in t]
    assert len(retry) == 1  # the retranslation got the reviewer's issue


def test_only_names_of_the_source_text_are_kept():
    c = Compendium()
    c.merge(
        [e("Roxy", gender="female", aliases=["la tutrice", "the tutor"])],
        source_text="Roxy smiled. The tutor nodded.",
    )
    assert c.entries == [e("Roxy", gender="female", aliases=["the tutor"])]


async def test_a_series_store_is_shared_live_and_written_to_every_member(db):
    import asyncio

    from sqlalchemy import select

    from app.db.database import async_session
    from app.db.models import Book, GlossaryEntry
    from app.knowledge.store import KnowledgeRegistry
    from app.models.schemas import GlossaryItem

    async with async_session() as s:
        books = [Book(filename=f"{n}.epub", original_path="x") for n in "ab"]
        s.add_all(books)
        await s.flush()
        a, b = (x.id for x in books)
        s.add(GlossaryEntry(book_id=a, source_term="Moon", target_term="Luna", user_edited=True))
        await s.commit()

    registry = KnowledgeRegistry()
    # both books start together: the second must still receive what the first loads
    first, second = await asyncio.gather(
        registry.acquire("glossary", "series:1", a, {a, b}),
        registry.acquire("glossary", "series:1", b, {a, b}),
    )
    assert first is second and [e.source_term for e in first.glossary.entries] == ["Moon"]

    # many concurrent learns: one row per term and book, nothing lost
    terms = [GlossaryItem(source_term=f"Star{n}", target_term=f"Stella{n}") for n in range(20)]
    await asyncio.gather(*(first.learn([t]) for t in terms))
    async with async_session() as s:
        rows = (await s.execute(select(GlossaryEntry.book_id, GlossaryEntry.source_term))).all()
    for book in (a, b):
        assert sorted(t for k, t in rows if k == book) == sorted(
            ["Moon", *(t.source_term for t in terms)]
        )

    registry.release(first)
    registry.release(second)
    again = await registry.acquire("glossary", "series:1", a, {a, b})
    assert again is not first  # released by every job: reloaded from the database
    assert len(again.glossary) == 21
