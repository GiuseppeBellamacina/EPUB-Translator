"""
Translator Agent — Translates text chunks with glossary awareness and context.
"""

import re

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from app.core.llm_factory import structured_chain
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
3. Preserve paragraph breaks exactly: output the same number of paragraphs, in the same order, \
separated by a blank line — never merge or split paragraphs
4. Inline markup appears as numbered placeholders like <1>...</1> or <2/>: keep every \
placeholder, wrapped around the translation of the same words; never translate, renumber or drop them
5. Report in new_terms any recurring name or term NOT already in the glossary that must be \
translated consistently later (characters, places, invented words, titles), with the translation \
you used; source_term must be copied exactly as it appears in the text. Omit common words
6. Maintain the same level of formality as the original
7. Do not add explanations or notes in the translation itself
8. The text may stop mid-sentence (it continues in the FOLLOWING TEXT, e.g. on the next \
page): stop your translation at the same point, without completing the sentence or adding \
closing quotation marks or punctuation

{style_instructions}""",
        ),
        (
            "human",
            """GLOSSARY (you MUST follow these translations):
{glossary}

CHAPTER CONTEXT: {chapter_summary}

PREVIOUS CONTEXT (for continuity, do NOT translate this):
{context}

FOLLOWING TEXT (comes right after, do NOT translate this):
{following}
{feedback}
---

The text has exactly {paragraph_count} paragraph(s); return exactly {paragraph_count}.

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
            lines.append(f"- {entry.source_term} → {entry.source_term} (keep exactly as written)")
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
    feedback: str = "",
    following: str = "",
    attempts: int | None = None,
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
        feedback: Reviewer issues from a rejected previous attempt, to fix this time
        following: Text right after the chunk (not translated), so sentences cut at a
            page end are recognised as unfinished
        attempts: Whole-call attempts (default: settings.chain_retries)

    Returns:
        TranslationResult with translated text and any new terms found
    """
    chain = structured_chain(TRANSLATION_PROMPT, llm, TranslationResult, attempts)

    result = await chain.ainvoke(
        {
            "text": text,
            "paragraph_count": len(split_paragraphs(text)),
            "context": context or "(Start of chapter)",
            "following": following or "(End of chapter)",
            "chapter_summary": chapter_summary or "No summary available",
            "glossary": _format_glossary(glossary),
            "style_instructions": _format_style(style_instructions),
            "feedback": _format_feedback(feedback),
            "source_language": source_language,
            "target_language": target_language,
        }
    )

    return result


def _format_feedback(feedback: str) -> str:
    if not feedback.strip():
        return ""
    return (
        "\nA REVIEWER REJECTED THE PREVIOUS TRANSLATION OF THIS TEXT. "
        f"Fix these issues:\n{feedback.strip()}\n"
    )


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def keep_unfinished(source: str, translation: str) -> str:
    """Drop a closing quote the model added to a quote left open in the source.

    A sentence cut at a page end (``“Why do they want to kill``) continues on the next
    page; models tend to close the quotation anyway, leaving a stray ``”``.
    """
    stripped = translation.rstrip()
    if source.count("“") > source.count("”") and stripped.endswith("”"):
        if translation.count("“") <= translation.count("”"):
            return stripped[:-1].rstrip()
    return translation


async def translate_blocks(
    llm: BaseChatModel, blocks: list[str], attempts: int = 2, **kwargs
) -> tuple[list[str], list[GlossaryItem]]:
    """Translate blocks as one chunk, guaranteeing one translation per block.

    The chunk is retried when the model merges/splits paragraphs; if it still
    does, or a call fails (e.g. a degenerate output hitting the token cap, which
    an identical request would just repeat), each block is translated on its own
    so alignment can never drift. ``kwargs`` are passed through to ``translate_chunk``.
    """
    if len(blocks) == 1:
        result = await translate_chunk(llm=llm, text=blocks[0], **kwargs)
        translation = " ".join(split_paragraphs(result.translated_text))
        return [keep_unfinished(blocks[0], translation)], result.new_terms

    for _ in range(attempts):
        try:
            result = await translate_chunk(llm=llm, text="\n\n".join(blocks), attempts=1, **kwargs)
        except Exception:
            break
        paragraphs = split_paragraphs(result.translated_text)
        if len(paragraphs) == len(blocks):
            return [keep_unfinished(s, t) for s, t in zip(blocks, paragraphs)], result.new_terms

    # Per block: each block's following text is the next block
    following = kwargs.pop("following", "")
    translations: list[str] = []
    new_terms: list[GlossaryItem] = []
    for i, block in enumerate(blocks):
        next_text = blocks[i + 1] if i + 1 < len(blocks) else following
        single, terms = await translate_blocks(llm, [block], following=next_text, **kwargs)
        translations += single
        new_terms += terms
    return translations, new_terms
