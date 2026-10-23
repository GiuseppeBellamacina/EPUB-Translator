"""Pydantic schemas for the translation pipeline.

Field descriptions are used directly by `llm.with_structured_output()` to steer
the model, so keep them clear and action-oriented.
"""

from typing import Literal

from pydantic import BaseModel, Field


class GlossaryItem(BaseModel):
    source_term: str = Field(description="The term as it appears in the source text")
    target_term: str = Field(description="The agreed translation to use consistently")
    context: str | None = Field(
        default=None, description="Brief note on usage/meaning to disambiguate the term"
    )
    do_not_translate: bool = Field(
        default=False,
        description="True for proper nouns, brand names, or terms to leave unchanged",
    )


class CompendiumEntry(BaseModel):
    """A character, place or other element of the book, with what a translator must know."""

    name: str = Field(description="The name as written in the source text (its fullest form)")
    kind: Literal["character", "place", "organization", "item", "other"] = Field(
        default="character", description="What the name refers to"
    )
    gender: Literal["male", "female", "unknown", "n/a"] = Field(
        default="unknown",
        description="For characters: the gender to use for agreement in the target language, "
        "only when the text makes it clear (pronouns, titles, descriptions); else unknown. "
        "n/a for places and things",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Other names, nicknames or titles the SOURCE text uses for the same entity "
        "(as written there, never translated)",
    )
    notes: str = Field(
        default="",
        description="One short sentence of facts that matter for the translation: role, "
        "relations, how they speak or address others, a fixed translation choice. Written in "
        "the language of the source text",
    )
    evidence: str = Field(
        default="",
        description="Only to correct a gender the COMPENDIUM lists: the few words of THIS "
        "passage, copied exactly, that prove the right one (e.g. 'she drew her sword')",
    )


class AnalysisResult(BaseModel):
    genre: str = Field(description="Literary genre, e.g. fantasy, sci-fi, romance, non-fiction")
    tone: str = Field(description="Overall tone, e.g. formal, casual, humorous, dark, poetic")
    characters: list[str] = Field(
        default_factory=list, description="Character names found in the text"
    )
    key_terms: list[GlossaryItem] = Field(
        default_factory=list,
        description="Recurring or domain-specific terms needing consistent translation",
    )
    do_not_translate: list[str] = Field(
        default_factory=list,
        description="Proper nouns, brand names, or terms that must NOT be translated; names "
        "without their titles (Ariel, not Princess Ariel: titles are translated)",
    )
    summary: str = Field(description="2-3 sentence summary of the content and themes")
    entities: list[CompendiumEntry] = Field(
        default_factory=list,
        description="Main characters (with their gender when the text makes it clear), places "
        "and other recurring elements, to start the book's compendium",
    )


class Doubt(BaseModel):
    quote: str = Field(description="The few SOURCE words you are unsure about, copied exactly")
    reason: str = Field(
        description="Why: gender not known yet, ambiguous reference, unknown term, wordplay..."
    )


class TranslationResult(BaseModel):
    translated_text: str = Field(
        description="The translated text, preserving paragraph breaks (\\n\\n) of the source"
    )
    new_terms: list[GlossaryItem] = Field(
        default_factory=list,
        description="New recurring terms encountered, to add to the shared glossary",
    )
    compendium_updates: list[CompendiumEntry] = Field(
        default_factory=list,
        description="Characters, places or other elements of THIS passage that are missing from "
        "the COMPENDIUM, or whose gender, aliases or notes this passage reveals; only facts "
        "stated or clearly implied by the text",
    )
    doubts: list[Doubt] = Field(
        default_factory=list,
        description="At most 3 places where you had to guess (a gender the text has not "
        "revealed yet, who a pronoun refers to, an unknown term, wordplay); they are revisited "
        "at the end of the book. Leave empty when sure",
    )


class DoubtResolution(BaseModel):
    """The end-of-book decision on a passage translated with doubts."""

    translation: str | None = Field(
        default=None,
        description="The corrected translation of the passage, as one paragraph, keeping "
        "inline placeholders like <1>...</1>; null when the current translation is right",
    )
    note: str = Field(default="", description="One short sentence: what was decided and why")


class ReviewIssue(BaseModel):
    severity: Literal["major", "minor"] = Field(
        description=(
            "major: meaning changed, content omitted or added, a glossary term not "
            "followed, a character given the wrong gender (against the compendium), text "
            "left untranslated, or an inline placeholder lost. "
            "minor: style, word choice or fluency preferences"
        )
    )
    description: str = Field(description="The specific problem, quoting the words involved")


class ReviewResult(BaseModel):
    """Approval is computed, not chosen by the model: no major issue, no glossary violation."""

    issues: list[ReviewIssue] = Field(
        default_factory=list,
        description="Real problems only; omit anything you consider acceptable",
    )
    glossary_violations: list[str] = Field(
        default_factory=list, description="Glossary terms translated inconsistently"
    )
    corrected_text: str | None = Field(
        default=None,
        description="Full corrected translation ONLY if there is a major issue or a glossary "
        "violation, with the same paragraphs; otherwise null",
    )

    @property
    def major_issues(self) -> list[str]:
        return [i.description for i in self.issues if i.severity == "major"]

    @property
    def approved(self) -> bool:
        return not self.major_issues and not self.glossary_violations
