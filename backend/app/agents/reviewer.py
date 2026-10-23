"""
Reviewer Agent — Validates translation quality, consistency, and glossary adherence.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from app.agents.compendium import render
from app.core.llm_factory import structured_chain
from app.models.schemas import CompendiumEntry, GlossaryItem, ReviewResult

REVIEW_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a translation quality reviewer. Your job is to verify that a translation:
1. Faithfully represents the original text's meaning
2. Follows the glossary consistently (MOST IMPORTANT)
3. Maintains natural flow in the target language
4. Preserves proper nouns and "do not translate" terms unchanged
5. Keeps the same tone and register as the original

Check for:
- Glossary violations (terms translated differently than specified)
- Proper nouns that were incorrectly translated
- Unnatural phrasing or awkward constructions
- Missing content or added content not in the original
- Inconsistent terminology within the chunk
- Characters given a gender that contradicts the COMPENDIUM (articles, adjectives, participles,
  pronouns): who "he"/"she"/"they" refers to may be named in the PREVIOUS CONTEXT

Classify every issue: "major" for real errors (meaning changed, content omitted or added,
glossary not followed, a character's gender against the compendium, text left untranslated,
inline placeholders like <1>...</1> lost),
"minor" for style or word-choice preferences. Never report something you consider
acceptable or correct. A translation with only minor issues is accepted as it is.
The text may end mid-sentence (it continues on the next page): that is not an issue.

{style_instructions}""",
        ),
        (
            "human",
            """GLOSSARY:
{glossary}

COMPENDIUM:
{compendium}

PREVIOUS CONTEXT (already translated, not to review):
{previous}

ORIGINAL TEXT ({source_language}):
{original_text}

TRANSLATION ({target_language}):
{translated_text}

Review the translation for accuracy and glossary adherence.""",
        ),
    ]
)


def _format_glossary(glossary: list[GlossaryItem]) -> str:
    """Format glossary entries for the prompt."""
    if not glossary:
        return "(No glossary entries)"

    lines = []
    for entry in glossary:
        if entry.do_not_translate:
            lines.append(f"- {entry.source_term} → {entry.source_term} (keep exactly as written)")
        else:
            lines.append(f"- {entry.source_term} → {entry.target_term}")
    return "\n".join(lines)


def _format_style(style_instructions: str) -> str:
    """Format optional user style instructions for the prompt."""
    if not style_instructions.strip():
        return ""
    return (
        "USER STYLE INSTRUCTIONS (the translation should respect these):\n"
        f"{style_instructions.strip()}"
    )


async def review_translation(
    llm: BaseChatModel,
    original_text: str,
    translated_text: str,
    glossary: list[GlossaryItem],
    source_language: str,
    target_language: str,
    style_instructions: str = "",
    compendium: list[CompendiumEntry] | None = None,
    previous: str = "",
) -> ReviewResult:
    """
    Review a translation for quality and glossary adherence.

    Args:
        llm: The language model to use
        original_text: The original source text
        translated_text: The translated text to review
        glossary: Glossary entries that must be followed
        source_language: Source language
        target_language: Target language
        style_instructions: Optional free-form user instructions on tone/register/style
        compendium: Compendium entries the text (or the text before it) names
        previous: Source text right before the reviewed one, to resolve pronouns

    Returns:
        ReviewResult with approval status, issues, and optional correction
    """
    chain = structured_chain(REVIEW_PROMPT, llm, ReviewResult)

    result = await chain.ainvoke(
        {
            "original_text": original_text,
            "translated_text": translated_text,
            "glossary": _format_glossary(glossary),
            "compendium": render(compendium or []),
            "previous": previous or "(Start of chapter)",
            "style_instructions": _format_style(style_instructions),
            "source_language": source_language,
            "target_language": target_language,
        }
    )

    return result
