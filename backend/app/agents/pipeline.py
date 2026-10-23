"""
Translation Pipeline — LangGraph orchestration of the agentic translation flow.

The per-chapter flow is modeled as a `StateGraph` with a Pydantic state:

    context ──▶ translate ──▶ review ──▶ learn ──▶ finalize ──▶ complete ──▶ END
       ▲            ▲           │                     │
       │            └── retry ──┘                     │
       └──────────────────── next chunk ◀─────────────┘

Only translate and review call the model. ``context`` picks the glossary terms and
compendium entries the chunk mentions (also in the text before it: a "she" may refer
to someone named earlier); ``learn`` folds what the accepted translation reported
into them; ``finalize`` enforces the glossary and emits the resume checkpoint.

The review step is optional (``enable_review``); a rejected chunk is retranslated
with the reviewer's issues in the prompt. A chunk whose translation fails is not
stored as translated: its blocks stay ``None`` (original kept), nothing is learned
from it, and its index is reported in ``failed_chunks`` so a later run can retry it.

The glossary and the compendium are single shared objects read live by every node,
so what one chunk/chapter learns is used everywhere from then on.

Nodes emit progress via `get_stream_writer()` (custom stream mode), which the
`TranslationPipeline` wrapper consumes and re-yields as `TranslationProgress`
events for the WebSocket layer.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from langchain_core.language_models import BaseChatModel
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, Field

from app.agents.analyzer import analyze_context
from app.agents.reviewer import review_translation
from app.agents.translator_agent import split_paragraphs, translate_blocks
from app.knowledge.store import CompendiumStore, GlossaryStore
from app.models.schemas import AnalysisResult, CompendiumEntry, Doubt, GlossaryItem
from app.services.chunker import Chunk, SmartChunker, TextBlock

MAX_DOUBTS = 3  # per chunk: the final review stays short


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
    trail_context: str = ""  # start of the next unit, following text of the last chunk
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
    glossary_context: list[GlossaryItem] = Field(default_factory=list)  # terms the chunk uses
    compendium_context: list[CompendiumEntry] = Field(default_factory=list)  # who/what it names
    current_blocks: list[str] = Field(default_factory=list)  # one translation per chunk block
    current_new_terms: list[GlossaryItem] = Field(default_factory=list)
    current_compendium: list[CompendiumEntry] = Field(default_factory=list)
    current_doubts: list[Doubt] = Field(default_factory=list)
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


def _placed_doubts(state: ChapterState) -> list[dict]:
    """The accepted translation's doubts, each on the block (of the chapter) that quotes it.

    Quotes not found in the chunk are dropped (invented by the model); at most
    ``MAX_DOUBTS`` per chunk.
    """
    chunk, offset = state.chunks[state.chunk_index], state.offsets[state.chunk_index]
    placed = []
    for doubt in state.current_doubts:
        quote = " ".join(doubt.quote.lower().split())
        for i, block in enumerate(chunk.blocks):
            if quote and quote in " ".join(block.text.lower().split()):
                placed.append(
                    {
                        "block": offset + i,
                        "quote": doubt.quote.strip(),
                        "reason": doubt.reason.strip(),
                        "source": block.text,
                        "translation": state.current_blocks[i],
                    }
                )
                break
    return placed[:MAX_DOUBTS]


def _following(state: ChapterState) -> str:
    """Text right after the current chunk: next chunk's first block, or the next unit."""
    if state.chunk_index + 1 < len(state.chunks):
        return state.chunks[state.chunk_index + 1].blocks[0].text
    return state.trail_context


def _previous(state: ChapterState) -> str:
    """Text right before the current chunk (its overlap, or the end of the previous unit)."""
    chunk = state.chunks[state.chunk_index]
    return chunk.context_text or (state.lead_context if state.chunk_index == 0 else "")


@dataclass(frozen=True)
class Features:
    """What a run uses (the ``RunConfig`` switches); everything is on by default."""

    analysis: bool = True  # the opening analysis (summary, first glossary/compendium)
    use_glossary: bool = True  # glossary terms in the prompts
    learn_glossary: bool = True  # new terms reported by the model join the glossary
    enforce_glossary: bool = True  # deterministic replacement of terms left untranslated
    use_compendium: bool = True
    learn_compendium: bool = True


def build_chapter_graph(
    llm: BaseChatModel,
    glossaries: GlossaryStore,
    compendiums: CompendiumStore,
    review_llm: BaseChatModel | None = None,
    features: Features = Features(),
) -> CompiledStateGraph:
    """Compile the per-chapter graph for a given model and the live knowledge stores."""
    glossary, compendium = glossaries.glossary, compendiums.compendium  # read live

    def context_node(state: ChapterState) -> dict[str, Any]:
        text, before = state.chunks[state.chunk_index].text, _previous(state)
        return {
            "glossary_context": glossary.relevant(text, before) if features.use_glossary else [],
            "compendium_context": (
                compendium.relevant(text, before) if features.use_compendium else []
            ),
        }

    async def translate_node(state: ChapterState) -> dict[str, Any]:
        writer = get_stream_writer()
        chunk = state.chunks[state.chunk_index]
        total = len(state.chunks)
        try:
            translations, new_terms, compendium_updates, doubts = await translate_blocks(
                llm,
                [b.text for b in chunk.blocks],
                context=_previous(state),
                chapter_summary=state.chapter_summary,
                glossary=state.glossary_context,
                compendium=state.compendium_context,
                source_language=state.source_language,
                target_language=state.target_language,
                style_instructions=state.style_instructions,
                feedback=state.feedback,
                following=_following(state),
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
                "current_blocks": [],
                "current_new_terms": [],
                "current_doubts": [],
                "translation_failed": True,
            }

        writer(
            {
                "event_type": "chunk_translated",
                "chunk_index": state.chunk_index,
                "total_chunks": total,
                "message": f"Chunk {state.chunk_index + 1}/{total} translated",
                # source text too: the UI shows original and translation side by side
                "data": {"translated_text": "\n\n".join(translations), "source_text": chunk.text},
            }
        )
        return {
            "current_blocks": translations,
            "current_new_terms": new_terms,
            "current_compendium": compendium_updates,
            "current_doubts": doubts,
            "translation_failed": False,
        }

    async def review_node(state: ChapterState) -> dict[str, Any]:
        writer = get_stream_writer()
        chunk = state.chunks[state.chunk_index]
        total = len(state.chunks)
        try:
            review = await review_translation(
                llm=review_llm or llm,
                original_text=chunk.text,
                translated_text=state.current_translation,
                glossary=state.glossary_context,
                compendium=state.compendium_context,
                previous=_previous(state),
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
                    "data": {"issues": review.major_issues + review.glossary_violations},
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
                [f"- {issue}" for issue in review.major_issues]
                + [f"- Glossary violation: {v}" for v in review.glossary_violations]
            )
        return updates

    async def learn_node(state: ChapterState) -> dict[str, Any]:
        """Fold what the accepted translation reported into the glossary and compendium
        (shared and persisted by the stores)."""
        writer = get_stream_writer()
        chunk = state.chunks[state.chunk_index]
        accepted = (
            await glossaries.learn(state.current_new_terms, source_text=chunk.text)
            if features.learn_glossary
            else []
        )
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
        # names may only occur in the text before the chunk ("she" in this chunk)
        genders = {e.name: e.gender for e in compendium.entries}  # merged before any await
        changed = (
            await compendiums.learn(
                state.current_compendium, source_text=_previous(state) + "\n" + chunk.text
            )
            if features.learn_compendium
            else []
        )
        if changed:
            # a male/female flip now (evidence stays on the entry: it is not the signal)
            corrected = [
                e.name for e in changed if {genders.get(e.name), e.gender} == {"male", "female"}
            ]
            writer(
                {
                    "event_type": "compendium_update",
                    "chunk_index": state.chunk_index,
                    "total_chunks": len(state.chunks),
                    "message": "Compendium: " + ", ".join(e.name for e in changed),
                    "data": {"entries": [e.model_dump() for e in changed], "corrected": corrected},
                }
            )
        doubts = _placed_doubts(state)
        if doubts:
            writer(
                {
                    "event_type": "doubt_flagged",
                    "chunk_index": state.chunk_index,
                    "total_chunks": len(state.chunks),
                    "message": f"{len(doubts)} doubt(s) bookmarked for the final review",
                    "data": {"doubts": doubts},
                }
            )
        return {}

    def finalize_node(state: ChapterState) -> dict[str, Any]:
        writer = get_stream_writer()
        offset = state.offsets[state.chunk_index]
        updates: dict[str, Any] = {
            "position": state.position + 1,
            "retries": 0,
            "feedback": "",
            "should_retry": False,
            "translation_failed": False,
            "current_new_terms": [],
            "current_compendium": [],
            "current_doubts": [],
            "current_blocks": [],
        }

        translations: list[str] | None = None
        if state.translation_failed:
            updates["failed_chunks"] = state.failed_chunks + [state.chunk_index]
        else:
            # only the passage's own terms: others would only risk spurious replacements
            translations = [
                glossary.enforce(t, state.glossary_context if features.enforce_glossary else [])
                for t in state.current_blocks
            ]
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
        if state.translation_failed:
            return "finalize"
        return "review" if state.enable_review else "learn"

    def route_after_review(state: ChapterState) -> str:
        return "translate" if state.should_retry else "learn"

    def route_after_finalize(state: ChapterState) -> str:
        return "context" if state.position < len(state.pending) else "complete"

    builder = StateGraph(ChapterState)
    builder.add_node("context", context_node)
    builder.add_node("translate", translate_node)
    builder.add_node("review", review_node)
    builder.add_node("learn", learn_node)
    builder.add_node("finalize", finalize_node)
    builder.add_node("complete", complete_node)

    builder.add_edge(START, "context")
    builder.add_edge("context", "translate")
    builder.add_conditional_edges(
        "translate", route_after_translate, ["review", "learn", "finalize"]
    )
    builder.add_conditional_edges("review", route_after_review, ["translate", "learn"])
    builder.add_edge("learn", "finalize")
    builder.add_conditional_edges("finalize", route_after_finalize, ["context", "complete"])
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
        review_llm: Model for the review (default: ``llm``). A small model is a poor
            judge of its own output: reviewing with a stronger one pays off.
        doubt_review: Revisit, at the end of the book, the passages the translator was
            unsure about (``translate_document``), with the review model
        features: What the run uses (analysis, glossary and compendium switches)
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
        review_llm: BaseChatModel | None = None,
        glossaries: GlossaryStore | None = None,
        compendiums: CompendiumStore | None = None,
        doubt_review: bool = True,
        features: Features = Features(),
    ):
        self.llm = llm
        self.review_llm = review_llm or llm
        self.doubt_review = doubt_review
        self.features = features
        self.source_language = source_language
        self.target_language = target_language
        self.chunker = chunker or SmartChunker()
        self.max_retries = max_retries
        self.style_instructions = style_instructions
        self.enable_review = enable_review
        # live stores (shared with other books of a series); in memory when not given
        self.glossaries = glossaries or GlossaryStore()
        self.compendiums = compendiums or CompendiumStore()
        self.book_summary: str = ""
        self._cancelled = False
        self.cancelled = asyncio.Event()  # wakes a caller waiting on a slow model call
        self._graph = build_chapter_graph(
            llm, self.glossaries, self.compendiums, review_llm, features
        )

    @property
    def glossary(self):
        return self.glossaries.glossary

    @property
    def compendium(self):
        return self.compendiums.compendium

    def cancel(self):
        """Signal cancellation to stop processing."""
        self._cancelled = True
        self.cancelled.set()

    def set_glossary(self, entries: list[GlossaryItem]):
        """Seed the glossary in memory (tests; jobs load the stores from the database)."""
        self.glossary.add(entries)

    def set_compendium(
        self, user: list[CompendiumEntry], learned: list[CompendiumEntry] | None = None
    ) -> None:
        """Seed the compendium in memory: the user's entries (never changed) first."""
        self.compendium.merge(user, user=True)
        self.compendium.merge(learned or [])

    async def analyze_chapter(self, text: str) -> AnalysisResult:
        """Run context analysis on the opening text and seed glossary and compendium."""
        result = await analyze_context(self.llm, text, self.source_language, self.target_language)
        if self.features.learn_glossary:
            await self.glossaries.learn(result.key_terms, source_text=text)
            await self.glossaries.learn(
                [
                    GlossaryItem(source_term=term, target_term=term, do_not_translate=True)
                    for term in result.do_not_translate
                ],
                source_text=text,
            )
        if self.features.learn_compendium:
            await self.compendiums.learn(result.entities, source_text=text)
        return result

    async def translate_chapter(
        self,
        blocks: list[TextBlock],
        chapter_index: int = 0,
        total_chapters: int = 1,
        previous: list[str | None] | None = None,
        lead_context: str = "",
        trail_context: str = "",
        chapter_summary: str = "",
    ) -> AsyncGenerator[TranslationProgress, None]:
        """
        Translate a chapter's blocks via the LangGraph pipeline: chunk → translate → review.

        ``previous`` is the resume checkpoint (one entry per block, None = to do):
        chunks whose blocks are all translated are skipped. Chunking is deterministic,
        so the same blocks always produce the same chunks. ``lead_context`` (the end
        of the previous unit) is the context of the first chunk; ``trail_context`` (the
        start of the next unit) tells the last chunk how its text continues.

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
                trail_context=trail_context,
                source_language=self.source_language,
                target_language=self.target_language,
                style_instructions=self.style_instructions,
                max_retries=self.max_retries,
                enable_review=self.enable_review,
            )
            # Each chunk runs context, translate/review (per attempt), learn and finalize,
            # plus a terminal complete node — budget generously to avoid recursion limits.
            recursion_limit = len(pending) * (5 + 2 * self.max_retries) + 10

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
