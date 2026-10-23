"""
Context Analyzer Agent — Analyzes a chapter to extract tone, genre, characters,
and builds an initial glossary of key terms.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from app.core.llm_factory import structured_chain
from app.models.schemas import AnalysisResult

ANALYSIS_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a literary analyst specializing in text analysis for translation purposes.
Analyze the text and produce a structured analysis that will guide translators.

Focus on:
- Recurring terminology that needs consistent translation (suggest a target term in {target_language})
- Character names (these should generally NOT be translated). Titles and ranks are translated: \
list the bare name in do_not_translate (Ariel) and a titled form in the key terms with its \
translation (Princess Ariel)
- Technical or domain-specific terms
- Culturally significant phrases that need careful handling
- The overall style and tone the translator should maintain
- Entities for the book's compendium: the main characters (with their gender when pronouns, \
titles or descriptions make it clear, aliases and a short note on who they are and how they \
speak) and the recurring places""",
        ),
        (
            "human",
            """Analyze this text (from {source_language}, to be translated to {target_language}):

{text}""",
        ),
    ]
)


async def analyze_context(
    llm: BaseChatModel,
    text: str,
    source_language: str,
    target_language: str,
) -> AnalysisResult:
    """
    Analyze a chapter's context to extract metadata and build initial glossary.

    Args:
        llm: The language model to use
        text: The full chapter text (plain text, not HTML)
        source_language: Source language name
        target_language: Target language name

    Returns:
        AnalysisResult with genre, tone, characters, key terms, and summary
    """
    chain = structured_chain(ANALYSIS_PROMPT, llm, AnalysisResult)

    # Truncate if too long (analysis doesn't need full text, first ~3000 tokens suffice)
    max_chars = 12000
    truncated_text = text[:max_chars] + ("..." if len(text) > max_chars else "")

    result = await chain.ainvoke(
        {
            "text": truncated_text,
            "source_language": source_language,
            "target_language": target_language,
        }
    )

    return result
