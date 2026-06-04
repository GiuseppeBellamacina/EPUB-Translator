"""
Translator Agent — Translates text chunks with glossary awareness and context.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from app.models.schemas import GlossaryItem, TranslationResult

TRANSLATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a professional literary translator. Translate text while maintaining:
- Natural flow and readability in the target language
- Consistent terminology as defined in the glossary
- The original tone, style, and register
- All formatting (paragraphs, emphasis, etc.)

CRITICAL RULES:
1. Follow the glossary strictly — use the exact translations specified
2. Do NOT translate terms marked as "do not translate"
3. Preserve paragraph breaks and text structure exactly
4. If you encounter new important terms not in the glossary, note them
5. Maintain the same level of formality as the original
6. Do not add explanations or notes in the translation itself

{style_instructions}""",
        ),
        (
            "human",
            """GLOSSARY (you MUST follow these translations):
{glossary}

CHAPTER CONTEXT: {chapter_summary}

PREVIOUS CONTEXT (for continuity, do NOT translate this):
{context}

---

TRANSLATE the following from {source_language} to {target_language}:

{text}""",
        ),
    ]
)


def _format_glossary(glossary: list[GlossaryItem]) -> str:
    """Format glossary entries for the prompt."""
    if not glossary:
        return "(No glossary entries yet)"

    lines = []
    for entry in glossary:
        if entry.do_not_translate:
            lines.append(f"- {entry.source_term} → [DO NOT TRANSLATE]")
        else:
            lines.append(f"- {entry.source_term} → {entry.target_term}")
    return "\n".join(lines)


def _format_style(style_instructions: str) -> str:
    """Format optional user style instructions for the prompt."""
    if not style_instructions.strip():
        return ""
    return (
        "USER STYLE INSTRUCTIONS (follow these closely, they override default style choices):\n"
        f"{style_instructions.strip()}"
    )


async def translate_chunk(
    llm: BaseChatModel,
    text: str,
    context: str,
    chapter_summary: str,
    glossary: list[GlossaryItem],
    source_language: str,
    target_language: str,
    style_instructions: str = "",
) -> TranslationResult:
    """
    Translate a text chunk with glossary awareness and context.

    Args:
        llm: The language model to use
        text: The text to translate
        context: Previous chunk text for continuity (not translated)
        chapter_summary: Brief summary of chapter context
        glossary: List of glossary entries to follow
        source_language: Source language
        target_language: Target language
        style_instructions: Optional free-form user instructions on tone/register/style

    Returns:
        TranslationResult with translated text and any new terms found
    """
    chain = TRANSLATION_PROMPT | llm.with_structured_output(TranslationResult)

    result = await chain.ainvoke(
        {
            "text": text,
            "context": context or "(Start of chapter)",
            "chapter_summary": chapter_summary or "No summary available",
            "glossary": _format_glossary(glossary),
            "style_instructions": _format_style(style_instructions),
            "source_language": source_language,
            "target_language": target_language,
        }
    )

    return result
