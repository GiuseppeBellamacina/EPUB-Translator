"""
Translation Pipeline — LangGraph orchestration of the agentic translation flow.

The per-chapter flow is modeled as a `StateGraph` with a Pydantic state:

    translate ──▶ review ──▶ finalize ──▶ complete ──▶ END
        ▲           │            │
        └── retry ──┘            └── next chunk ──▶ translate

Nodes emit progress via `get_stream_writer()` (custom stream mode), which the
`TranslationPipeline` wrapper consumes and re-yields as `TranslationProgress`
events for the WebSocket layer.
"""

import re
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from langchain_core.language_models import BaseChatModel
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, Field

from app.agents.analyzer import analyze_context
from app.agents.reviewer import review_translation
from app.agents.translator_agent import translate_chunk
from app.models.schemas import AnalysisResult, GlossaryItem
from app.services.chunker import Chunk, SmartChunker


@dataclass
class TranslationProgress:
    """Progress event emitted during translation."""

    event_type: (
        str  # chapter_start, chunk_translated, chunk_reviewed, chapter_done, glossary_update, error
    )
    chapter_index: int = 0
    total_chapters: int = 0
    chunk_index: int = 0
    total_chunks: int = 0
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def _merge_glossary(
    existing: list[GlossaryItem], new_entries: list[GlossaryItem]
) -> list[GlossaryItem]:
    """Append new entries to a glossary, skipping duplicate source terms."""
    result = list(existing)
    seen = {e.source_term.lower() for e in result}
    for entry in new_entries:
        key = entry.source_term.lower()
        if key not in seen:
            result.append(entry)
            seen.add(key)
    return result


def _match_case(source: str, replacement: str) -> str:
    """Mirror the casing of the matched source onto the replacement."""
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _enforce_glossary(text: str, glossary: list[GlossaryItem]) -> str:
    """Deterministically enforce glossary terms left untranslated by the LLM.

    For each glossary entry that should be translated, replace any remaining
    whole-word occurrences of the source term with the target term, mirroring
    the original casing. This guarantees consistency for terms (e.g. proper
    names) the model may have missed in some occurrences.
    """
    if not text or not glossary:
        return text
    for entry in glossary:
        if entry.do_not_translate or not entry.target_term.strip():
            continue
        pattern = re.compile(r"\b" + re.escape(entry.source_term) + r"\b", re.IGNORECASE)
        text = pattern.sub(lambda m: _match_case(m.group(0), entry.target_term), text)
    return text


class ChapterState(BaseModel):
    """Pydantic state shared across the per-chapter translation graph."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Inputs
    chunks: list[Chunk]
    glossary: list[GlossaryItem] = Field(default_factory=list)
    chapter_summary: str = ""
    source_language: str = "english"
    target_language: str = "italian"
    style_instructions: str = ""
    max_retries: int = 1

    # Per-chunk working state
    chunk_index: int = 0
    retries: int = 0
    current_translation: str = ""
    current_new_terms: list[GlossaryItem] = Field(default_factory=list)
    review_approved: bool = False
    should_retry: bool = False
    translation_failed: bool = False

    # Output
    translated_blocks: list[str] = Field(default_factory=list)


def build_chapter_graph(llm: BaseChatModel) -> CompiledStateGraph:
    """Compile the per-chapter translation graph for a given model."""

    async def translate_node(state: ChapterState) -> dict[str, Any]:
        writer = get_stream_writer()
        chunk = state.chunks[state.chunk_index]
        total = len(state.chunks)
        try:
            result = await translate_chunk(
                llm=llm,
                text=chunk.text,
                context=chunk.context_text,
                chapter_summary=state.chapter_summary,
                glossary=state.glossary,
                source_language=state.source_language,
                target_language=state.target_language,
                style_instructions=state.style_instructions,
            )
        except Exception as e:
            writer(
                {
                    "event_type": "error",
                    "chunk_index": state.chunk_index,
                    "total_chunks": total,
                    "message": f"Translation error on chunk {state.chunk_index + 1}: {e}",
                }
            )
            return {
                "current_translation": chunk.text,
                "current_new_terms": [],
                "translation_failed": True,
            }

        writer(
            {
                "event_type": "chunk_translated",
                "chunk_index": state.chunk_index,
                "total_chunks": total,
                "message": f"Chunk {state.chunk_index + 1}/{total} translated",
                "data": {"translated_text": result.translated_text},
            }
        )
        return {
            "current_translation": result.translated_text,
            "current_new_terms": result.new_terms,
            "translation_failed": False,
        }

    async def review_node(state: ChapterState) -> dict[str, Any]:
        writer = get_stream_writer()
        chunk = state.chunks[state.chunk_index]
        total = len(state.chunks)
        try:
            review = await review_translation(
                llm=llm,
                original_text=chunk.text,
                translated_text=state.current_translation,
                glossary=state.glossary,
                source_language=state.source_language,
                target_language=state.target_language,
                style_instructions=state.style_instructions,
            )
        except Exception:
            # If review fails, accept the translation as-is.
            return {"review_approved": True, "should_retry": False}

        if review.approved:
            writer(
                {
                    "event_type": "chunk_reviewed",
                    "chunk_index": state.chunk_index,
                    "total_chunks": total,
                    "message": f"Chunk {state.chunk_index + 1}/{total} approved",
                }
            )
            return {"review_approved": True, "should_retry": False}

        # Not approved: keep the corrected text (if any) as the current best.
        corrected = review.corrected_text or state.current_translation
        should_retry = state.retries < state.max_retries
        if should_retry:
            writer(
                {
                    "event_type": "chunk_rejected",
                    "chunk_index": state.chunk_index,
                    "total_chunks": total,
                    "message": f"Chunk {state.chunk_index + 1}/{total} rejected by reviewer, retranslating...",
                }
            )
        else:
            writer(
                {
                    "event_type": "chunk_accepted",
                    "chunk_index": state.chunk_index,
                    "total_chunks": total,
                    "message": f"Chunk {state.chunk_index + 1}/{total} accepted after max retries",
                    "data": {"translated_text": corrected},
                }
            )
        updates: dict[str, Any] = {
            "review_approved": False,
            "current_translation": corrected,
            "should_retry": should_retry,
        }
        if should_retry:
            updates["retries"] = state.retries + 1
        return updates

    def finalize_node(state: ChapterState) -> dict[str, Any]:
        writer = get_stream_writer()
        glossary = _merge_glossary(state.glossary, state.current_new_terms)
        if state.current_new_terms:
            writer(
                {
                    "event_type": "glossary_update",
                    "chunk_index": state.chunk_index,
                    "total_chunks": len(state.chunks),
                    "message": f"Added {len(state.current_new_terms)} new glossary terms",
                    "data": {"new_terms": [t.model_dump() for t in state.current_new_terms]},
                }
            )
        return {
            "translated_blocks": state.translated_blocks
            + [_enforce_glossary(state.current_translation, glossary)],
            "glossary": glossary,
            "chunk_index": state.chunk_index + 1,
            "retries": 0,
            "should_retry": False,
            "translation_failed": False,
            "current_new_terms": [],
        }

    def complete_node(state: ChapterState) -> dict[str, Any]:
        writer = get_stream_writer()
        writer(
            {
                "event_type": "chapter_complete",
                "total_chunks": len(state.chunks),
                "data": {
                    "translated_blocks": state.translated_blocks,
                    "glossary": [e.model_dump() for e in state.glossary],
                },
            }
        )
        return {}

    def route_after_translate(state: ChapterState) -> str:
        return "finalize" if state.translation_failed else "review"

    def route_after_review(state: ChapterState) -> str:
        return "translate" if state.should_retry else "finalize"

    def route_after_finalize(state: ChapterState) -> str:
        return "translate" if state.chunk_index < len(state.chunks) else "complete"

    builder = StateGraph(ChapterState)
    builder.add_node("translate", translate_node)
    builder.add_node("review", review_node)
    builder.add_node("finalize", finalize_node)
    builder.add_node("complete", complete_node)

    builder.add_edge(START, "translate")
    builder.add_conditional_edges("translate", route_after_translate, ["review", "finalize"])
    builder.add_conditional_edges("review", route_after_review, ["translate", "finalize"])
    builder.add_conditional_edges("finalize", route_after_finalize, ["translate", "complete"])
    builder.add_edge("complete", END)

    return builder.compile()


class TranslationPipeline:
    """
    Full agentic translation pipeline backed by a LangGraph `StateGraph`.

    Args:
        llm: The language model for all agents
        source_language: Source language name
        target_language: Target language name
        chunker: SmartChunker instance (or creates default)
        max_retries: Max translation retry attempts on review failure
        style_instructions: Optional free-form user instructions on tone/style
    """

    def __init__(
        self,
        llm: BaseChatModel,
        source_language: str = "english",
        target_language: str = "italian",
        chunker: SmartChunker | None = None,
        max_retries: int = 1,
        style_instructions: str = "",
    ):
        self.llm = llm
        self.source_language = source_language
        self.target_language = target_language
        self.chunker = chunker or SmartChunker()
        self.max_retries = max_retries
        self.style_instructions = style_instructions
        self.glossary: list[GlossaryItem] = []
        self.book_summary: str = ""
        self._cancelled = False
        self._graph = build_chapter_graph(llm)

    def cancel(self):
        """Signal cancellation to stop processing."""
        self._cancelled = True

    def set_glossary(self, entries: list[GlossaryItem]):
        """Set initial glossary (e.g., from user edits or previous sessions)."""
        self.glossary = list(entries)

    def add_glossary_entries(self, entries: list[GlossaryItem]):
        """Add new entries to glossary, avoiding duplicates."""
        self.glossary = _merge_glossary(self.glossary, entries)

    async def analyze_chapter(self, text: str) -> AnalysisResult:
        """Run context analysis on a chapter and seed the glossary."""
        result = await analyze_context(self.llm, text, self.source_language, self.target_language)
        self.add_glossary_entries(result.key_terms)
        self.add_glossary_entries(
            [
                GlossaryItem(source_term=term, target_term=term, do_not_translate=True)
                for term in result.do_not_translate
            ]
        )
        return result

    async def translate_chapter(
        self,
        html_content: str | bytes,
        chapter_index: int = 0,
        total_chapters: int = 1,
        chapter_summary: str = "",
    ) -> AsyncGenerator[TranslationProgress, None]:
        """
        Translate a chapter via the LangGraph pipeline: chunk → translate → review → merge.

        Yields TranslationProgress events for real-time UI updates. The final
        event contains the translated text in data["translated_blocks"].
        """
        if self._cancelled:
            return

        yield TranslationProgress(
            event_type="chapter_start",
            chapter_index=chapter_index,
            total_chapters=total_chapters,
            message=f"Starting chapter {chapter_index + 1}/{total_chapters}",
        )

        chunks = self.chunker.chunk_html(html_content)
        total_chunks = len(chunks)

        if total_chunks == 0:
            yield TranslationProgress(
                event_type="chapter_done",
                chapter_index=chapter_index,
                total_chapters=total_chapters,
                message="Chapter has no translatable content",
                data={"translated_blocks": []},
            )
            return

        init_state = ChapterState(
            chunks=chunks,
            glossary=self.glossary,
            chapter_summary=chapter_summary or self.book_summary,
            source_language=self.source_language,
            target_language=self.target_language,
            style_instructions=self.style_instructions,
            max_retries=self.max_retries,
        )

        translated_blocks: list[str] = []
        # Each chunk can fan out to translate/review/(retry)/finalize, plus a
        # terminal complete node — budget generously to avoid recursion limits.
        recursion_limit = total_chunks * (4 + 2 * self.max_retries) + 10

        async for event in self._graph.astream(
            init_state,
            stream_mode="custom",
            config={"recursion_limit": recursion_limit},
        ):
            if self._cancelled:
                return

            event_type = event.get("event_type", "")

            if event_type == "chapter_complete":
                data = event.get("data", {})
                translated_blocks = data.get("translated_blocks", [])
                self.glossary = [GlossaryItem(**g) for g in data.get("glossary", [])]
                continue

            yield TranslationProgress(
                event_type=event_type,
                chapter_index=chapter_index,
                total_chapters=total_chapters,
                chunk_index=event.get("chunk_index", 0),
                total_chunks=event.get("total_chunks", total_chunks),
                message=event.get("message", ""),
                data=event.get("data", {}),
            )

        yield TranslationProgress(
            event_type="chapter_done",
            chapter_index=chapter_index,
            total_chapters=total_chapters,
            message=f"Chapter {chapter_index + 1}/{total_chapters} completed",
            data={"translated_blocks": translated_blocks},
        )
