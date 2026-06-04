"""Pydantic schemas for the translation pipeline.

Field descriptions are used directly by `llm.with_structured_output()` to steer
the model, so keep them clear and action-oriented.
"""

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


class ReviewResult(BaseModel):
    approved: bool = Field(description="True if the translation is accurate and consistent")
    issues: list[str] = Field(
        default_factory=list, description="Specific problems found, empty if approved"
    )
    corrected_text: str | None = Field(
        default=None, description="Improved translation when not approved, otherwise null"
    )
    glossary_violations: list[str] = Field(
        default_factory=list, description="Glossary terms translated inconsistently"
    )
