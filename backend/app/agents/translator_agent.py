"""
Translator Agent — Translates text chunks with glossary awareness and context.
"""

import re

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from app.core.llm_factory import structured_chain
from app.knowledge.compendium import render
from app.models.schemas import CompendiumEntry, Doubt, GlossaryItem, TranslationResult

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
9. Use the COMPENDIUM: give each character the listed gender in every agreement (articles, \
adjectives, participles, pronouns) and follow its notes. This includes what characters say \
about themselves in the first person: work out who speaks each line (usually named around it) \
and agree with that speaker's gender. When a character's gender is unknown and the passage \
does not reveal it, prefer wording that does not commit to a gender
10. Report in compendium_updates what THIS passage reveals that the COMPENDIUM lacks: new \
characters (with their gender when pronouns, titles or descriptions make it clear), places \
and other recurring elements, new aliases, and short notes useful to translate them \
consistently. Only facts stated or clearly implied by the text; never repeat what is listed. \
When the passage clearly contradicts a listed gender, report the entry with the right gender \
and, in evidence, the words of the passage that prove it
11. Report in doubts (at most 3) the places where you had to guess: a gender the text has not \
revealed yet, who a pronoun refers to, a first-person line whose speaker you could not identify \
for sure (its agreements depend on the speaker), an unknown term, wordplay. They are revisited \
at the end of the book, when more is known. Never report what you are sure about

{style_instructions}""",
        ),
        (
            "human",
            """GLOSSARY (you MUST follow these translations):
{glossary}

COMPENDIUM (characters, places and other elements named here or just before):
{compendium}

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
    compendium: list[CompendiumEntry] | None = None,
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
        compendium: Compendium entries the chunk (or the text before it) names

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
            "compendium": render(compendium or []),
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


def aligned(sources: list[str], translations: list[str]) -> bool:
    """One translation per block, each of a plausible length for its block.

    A model may drop a short block (a page header) and split another paragraph in two:
    the count still matches, but the translations land on the wrong blocks. The bounds
    are loose (5x either way: CJK ↔ Latin scripts) and still catch a paragraph moved
    onto a one-line header.
    """
    if len(sources) != len(translations):
        return False
    for source, translation in zip(sources, translations):
        s, t = len(source.strip()), len(translation.strip())
        if t > 5 * s + 40 or t < s / 5 - 20:
            return False
    return True


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
) -> tuple[list[str], list[GlossaryItem], list[CompendiumEntry], list[Doubt]]:
    """Translate blocks as one chunk, guaranteeing one translation per block.

    Returns the translations, the new glossary terms, the compendium updates and the doubts.
    The chunk is retried when the model merges/splits paragraphs; if it still
    does, or a call fails (e.g. a degenerate output hitting the token cap, which
    an identical request would just repeat), each block is translated on its own
    so alignment can never drift. ``kwargs`` are passed through to ``translate_chunk``.
    """
    if len(blocks) == 1:
        result = await translate_chunk(llm=llm, text=blocks[0], **kwargs)
        translation = " ".join(split_paragraphs(result.translated_text))
        return (
            [keep_unfinished(blocks[0], translation)],
            result.new_terms,
            result.compendium_updates,
            result.doubts,
        )

    for _ in range(attempts):
        try:
            result = await translate_chunk(llm=llm, text="\n\n".join(blocks), attempts=1, **kwargs)
        except Exception:
            break
        paragraphs = split_paragraphs(result.translated_text)
        if aligned(blocks, paragraphs):
            translations = [keep_unfinished(s, t) for s, t in zip(blocks, paragraphs)]
            return translations, result.new_terms, result.compendium_updates, result.doubts

    # Per block: each block's following text is the next block
    following = kwargs.pop("following", "")
    translations: list[str] = []
    new_terms: list[GlossaryItem] = []
    updates: list[CompendiumEntry] = []
    doubts: list[Doubt] = []
    for i, block in enumerate(blocks):
        next_text = blocks[i + 1] if i + 1 < len(blocks) else following
        single, terms, found, unsure = await translate_blocks(
            llm, [block], following=next_text, **kwargs
        )
        translations += single
        new_terms += terms
        updates += found
        doubts += unsure
    return translations, new_terms, updates, doubts
