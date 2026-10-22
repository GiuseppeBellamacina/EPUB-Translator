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
        description="Proper nouns, brand names, or terms that must NOT be translated",
    )
    summary: str = Field(description="2-3 sentence summary of the content and themes")


class TranslationResult(BaseModel):
    translated_text: str = Field(
        description="The translated text, preserving paragraph breaks (\\n\\n) of the source"
    )
    new_terms: list[GlossaryItem] = Field(
        default_factory=list,
        description="New recurring terms encountered, to add to the shared glossary",
    )


class ReviewIssue(BaseModel):
    severity: Literal["major", "minor"] = Field(
        description=(
            "major: meaning changed, content omitted or added, a glossary term not "
            "followed, text left untranslated, or an inline placeholder lost. "
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
