"""
Translation Pipeline — LangGraph orchestration of the agentic translation flow.

The per-chapter flow is modeled as a `StateGraph` with a Pydantic state:

    translate ──▶ review ──▶ finalize ──▶ complete ──▶ END
        ▲           │            │
        └── retry ──┘            └── next chunk ──▶ translate

The review step is optional (``enable_review``); a rejected chunk is retranslated
with the reviewer's issues in the prompt. A chunk whose translation fails is not
stored as translated: its blocks stay ``None`` (original kept) and its index is
reported in ``failed_chunks`` so a later run can retry it.

The glossary is a single shared ``Glossary`` read live by every node, so terms
learned in one chunk/chapter are used everywhere from then on.

Nodes emit progress via `get_stream_writer()` (custom stream mode), which the
`TranslationPipeline` wrapper consumes and re-yields as `TranslationProgress`
events for the WebSocket layer.
"""

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from langchain_core.language_models import BaseChatModel
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, Field

from app.agents.analyzer import analyze_context
from app.agents.glossary import Glossary
from app.agents.reviewer import review_translation
from app.agents.translator_agent import split_paragraphs, translate_blocks
from app.models.schemas import AnalysisResult, GlossaryItem
from app.services.chunker import Chunk, SmartChunker, TextBlock


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


class ChapterState(BaseModel):
    """Pydantic state shared across the per-chapter translation graph."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Inputs
    chunks: list[Chunk]
    chapter_summary: str = ""
    lead_context: str = ""  # end of the previous unit, context for the first chunk
    source_language: str = "english"
    target_language: str = "italian"
    style_instructions: str = ""
    max_retries: int = 1
    enable_review: bool = True

    offsets: list[int]  # index of each chunk's first block in translated_blocks
    pending: list[int]  # chunk indexes still to translate (resume skips finished ones)

    # Per-chunk working state
    position: int = 0  # index into `pending`
    retries: int = 0
    current_blocks: list[str] = Field(default_factory=list)  # one translation per chunk block
    current_new_terms: list[GlossaryItem] = Field(default_factory=list)
    feedback: str = ""  # reviewer issues for the retranslation
    should_retry: bool = False
    translation_failed: bool = False

    # Output: one translation per block of the chapter (None = not translated / failed,
    # keep original). Starts from the resume checkpoint.
    translated_blocks: list[str | None]
    failed_chunks: list[int] = Field(default_factory=list)

    @property
    def chunk_index(self) -> int:
        return self.pending[self.position]

    @property
    def current_translation(self) -> str:
        return "\n\n".join(self.current_blocks)


def build_chapter_graph(llm: BaseChatModel, glossary: Glossary) -> CompiledStateGraph:
    """Compile the per-chapter translation graph for a given model and shared glossary."""

    async def translate_node(state: ChapterState) -> dict[str, Any]:
        writer = get_stream_writer()
        chunk = state.chunks[state.chunk_index]
        total = len(state.chunks)
        try:
            translations, new_terms = await translate_blocks(
                llm,
                [b.text for b in chunk.blocks],
                context=chunk.context_text
                or (state.lead_context if state.chunk_index == 0 else ""),
                chapter_summary=state.chapter_summary,
                glossary=glossary.relevant(chunk.context_text + "\n" + chunk.text),
                source_language=state.source_language,
                target_language=state.target_language,
                style_instructions=state.style_instructions,
                feedback=state.feedback,
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
            return {"current_blocks": [], "current_new_terms": [], "translation_failed": True}

        writer(
            {
                "event_type": "chunk_translated",
                "chunk_index": state.chunk_index,
                "total_chunks": total,
                "message": f"Chunk {state.chunk_index + 1}/{total} translated",
                "data": {"translated_text": "\n\n".join(translations)},
            }
        )
        return {
            "current_blocks": translations,
            "current_new_terms": new_terms,
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
                glossary=glossary.relevant(chunk.text),
                source_language=state.source_language,
                target_language=state.target_language,
                style_instructions=state.style_instructions,
            )
        except Exception:
            # If review fails, accept the translation as-is.
            return {"should_retry": False}

        if review.approved:
            writer(
                {
                    "event_type": "chunk_reviewed",
                    "chunk_index": state.chunk_index,
                    "total_chunks": total,
                    "message": f"Chunk {state.chunk_index + 1}/{total} approved",
                }
            )
            return {"should_retry": False}

        # Not approved: keep the corrected text as the current best, but only if it
        # still has one paragraph per block (otherwise it would break alignment).
        corrected_blocks = split_paragraphs(review.corrected_text or "")
        if len(corrected_blocks) != len(state.current_blocks):
            corrected_blocks = state.current_blocks
        corrected = "\n\n".join(corrected_blocks)
        should_retry = state.retries < state.max_retries
        if should_retry:
            writer(
                {
                    "event_type": "chunk_rejected",
                    "chunk_index": state.chunk_index,
                    "total_chunks": total,
                    "message": f"Chunk {state.chunk_index + 1}/{total} rejected by reviewer, "
                    "retranslating...",
                    "data": {"issues": review.issues + review.glossary_violations},
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
        updates: dict[str, Any] = {"current_blocks": corrected_blocks, "should_retry": should_retry}
        if should_retry:
            updates["retries"] = state.retries + 1
            updates["feedback"] = "\n".join(
                [f"- {issue}" for issue in review.issues]
                + [f"- Glossary violation: {v}" for v in review.glossary_violations]
            )
        return updates

    def finalize_node(state: ChapterState) -> dict[str, Any]:
        writer = get_stream_writer()
        chunk = state.chunks[state.chunk_index]
        offset = state.offsets[state.chunk_index]
        updates: dict[str, Any] = {
            "position": state.position + 1,
            "retries": 0,
            "feedback": "",
            "should_retry": False,
            "translation_failed": False,
            "current_new_terms": [],
            "current_blocks": [],
        }

        translations: list[str] | None = None
        if state.translation_failed:
            updates["failed_chunks"] = state.failed_chunks + [state.chunk_index]
        else:
            accepted = glossary.add(state.current_new_terms, source_text=chunk.text)
            if accepted:
                writer(
                    {
                        "event_type": "glossary_update",
                        "chunk_index": state.chunk_index,
                        "total_chunks": len(state.chunks),
                        "message": f"Added {len(accepted)} new glossary terms",
                        "data": {"new_terms": [t.model_dump() for t in accepted]},
                    }
                )
            translations = [glossary.enforce(t) for t in state.current_blocks]
            blocks = list(state.translated_blocks)
            blocks[offset : offset + len(translations)] = translations
            updates["translated_blocks"] = blocks

        # Checkpoint: the caller persists this so an interrupted job resumes here.
        writer(
            {
                "event_type": "chunk_done",
                "chunk_index": state.chunk_index,
                "total_chunks": len(state.chunks),
                "data": {
                    "offset": offset,
                    "translations": translations,
                    "total_blocks": len(state.translated_blocks),
                },
            }
        )
        return updates

    def complete_node(state: ChapterState) -> dict[str, Any]:
        writer = get_stream_writer()
        writer(
            {
                "event_type": "chapter_complete",
                "total_chunks": len(state.chunks),
                "data": {
                    "translated_blocks": state.translated_blocks,
                    "failed_chunks": state.failed_chunks,
                },
            }
        )
        return {}

    def route_after_translate(state: ChapterState) -> str:
        if state.translation_failed or not state.enable_review:
            return "finalize"
        return "review"

    def route_after_review(state: ChapterState) -> str:
        return "translate" if state.should_retry else "finalize"

    def route_after_finalize(state: ChapterState) -> str:
        return "translate" if state.position < len(state.pending) else "complete"

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
        enable_review: Run the reviewer on every chunk (doubles the LLM calls)
    """

    def __init__(
        self,
        llm: BaseChatModel,
        source_language: str = "english",
        target_language: str = "italian",
        chunker: SmartChunker | None = None,
        max_retries: int = 1,
        style_instructions: str = "",
        enable_review: bool = True,
    ):
        self.llm = llm
        self.source_language = source_language
        self.target_language = target_language
        self.chunker = chunker or SmartChunker()
        self.max_retries = max_retries
        self.style_instructions = style_instructions
        self.enable_review = enable_review
        self.glossary = Glossary()
        self.book_summary: str = ""
        self._cancelled = False
        self._graph = build_chapter_graph(llm, self.glossary)

    def cancel(self):
        """Signal cancellation to stop processing."""
        self._cancelled = True

    def set_glossary(self, entries: list[GlossaryItem]):
        """Seed the glossary (e.g., from user edits or previous sessions)."""
        self.glossary.add(entries)

    def add_glossary_entries(self, entries: list[GlossaryItem]) -> list[GlossaryItem]:
        """Add new entries to glossary, never overriding existing ones."""
        return self.glossary.add(entries)

    async def analyze_chapter(self, text: str) -> AnalysisResult:
        """Run context analysis on a chapter and seed the glossary."""
        result = await analyze_context(self.llm, text, self.source_language, self.target_language)
        self.glossary.add(result.key_terms, source_text=text)
        self.glossary.add(
            [
                GlossaryItem(source_term=term, target_term=term, do_not_translate=True)
                for term in result.do_not_translate
            ],
            source_text=text,
        )
        return result

    async def translate_chapter(
        self,
        blocks: list[TextBlock],
        chapter_index: int = 0,
        total_chapters: int = 1,
        previous: list[str | None] | None = None,
        lead_context: str = "",
        chapter_summary: str = "",
    ) -> AsyncGenerator[TranslationProgress, None]:
        """
        Translate a chapter's blocks via the LangGraph pipeline: chunk → translate → review.

        ``previous`` is the resume checkpoint (one entry per block, None = to do):
        chunks whose blocks are all translated are skipped. Chunking is deterministic,
        so the same blocks always produce the same chunks. ``lead_context`` (the end
        of the previous unit) is the context of the first chunk.

        Yields TranslationProgress events, including a ``chunk_done`` checkpoint per
        chunk. The final ``chapter_done`` event carries ``translated_blocks`` (one per
        block, None where a chunk failed) and ``failed_chunks``.
        """
        if self._cancelled:
            return

        chunks = self.chunker.create_chunks(blocks)
        offsets, total_blocks = [], 0
        for chunk in chunks:
            offsets.append(total_blocks)
            total_blocks += len(chunk.blocks)
        translated: list[str | None] = (
            list(previous) if previous and len(previous) == total_blocks else [None] * total_blocks
        )
        pending = [
            i
            for i, chunk in enumerate(chunks)
            if any(t is None for t in translated[offsets[i] : offsets[i] + len(chunk.blocks)])
        ]

        yield TranslationProgress(
            event_type="chapter_start",
            chapter_index=chapter_index,
            total_chapters=total_chapters,
            total_chunks=len(chunks),
            message=f"Starting chapter {chapter_index + 1}/{total_chapters}"
            + (f" (resuming, {len(pending)}/{len(chunks)} chunks left)" if previous else ""),
        )

        result: dict[str, Any] = {"translated_blocks": translated, "failed_chunks": []}
        if pending:
            init_state = ChapterState(
                chunks=chunks,
                offsets=offsets,
                pending=pending,
                translated_blocks=translated,
                chapter_summary=chapter_summary or self.book_summary,
                lead_context=lead_context,
                source_language=self.source_language,
                target_language=self.target_language,
                style_instructions=self.style_instructions,
                max_retries=self.max_retries,
                enable_review=self.enable_review,
            )
            # Each chunk can fan out to translate/review/(retry)/finalize, plus a
            # terminal complete node — budget generously to avoid recursion limits.
            recursion_limit = len(pending) * (4 + 2 * self.max_retries) + 10

            async for event in self._graph.astream(
                init_state,
                stream_mode="custom",
                config={"recursion_limit": recursion_limit},
            ):
                event_type = event.get("event_type", "")
                if event_type == "chapter_complete":
                    result = event.get("data", {})
                    continue

                # Yield before checking cancellation: a finished chunk's checkpoint
                # must reach the caller even if the job is being stopped.
                yield TranslationProgress(
                    event_type=event_type,
                    chapter_index=chapter_index,
                    total_chapters=total_chapters,
                    chunk_index=event.get("chunk_index", 0),
                    total_chunks=event.get("total_chunks", len(chunks)),
                    message=event.get("message", ""),
                    data=event.get("data", {}),
                )
                if self._cancelled:
                    return

        failed = result.get("failed_chunks", [])
        yield TranslationProgress(
            event_type="chapter_done",
            chapter_index=chapter_index,
            total_chapters=total_chapters,
            total_chunks=len(chunks),
            message=f"Chapter {chapter_index + 1}/{total_chapters} completed"
            + (f" ({len(failed)} chunk(s) failed)" if failed else ""),
            data=result,
        )
