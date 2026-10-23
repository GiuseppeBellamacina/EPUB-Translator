"""
Translation Service — translate a whole document, resumable and concurrent.

Phases:
1. Analysis (skipped when resuming with a stored analysis): seeds glossary and compendium.
2. Units (chapters/pages) run as concurrent tasks, at most ``max_concurrency`` at
   a time; their events are merged into one stream. Units already completed are
   skipped; partially translated units resume from their per-block checkpoint.
3. The output is written in the input format from all unit translations.

Every event is yielded to the caller, which persists checkpoints (``chunk_done``,
``chapter_saved``, ``glossary_update``, ``analysis_complete``) as they arrive.
"""

import asyncio
from collections.abc import AsyncGenerator, Collection
from pathlib import Path
from typing import Any

from app.agents.pipeline import TranslationPipeline, TranslationProgress
from app.services.chunker import SmartChunker
from app.services.documents import Document, Translations

ANALYSIS_MIN_CHARS = 500
ANALYSIS_MAX_CHARS = 12000  # analyzer truncation (agents/analyzer.py)


def analysis_text(doc: Document, max_chars: int = ANALYSIS_MAX_CHARS) -> str:
    """Text for the analyzer: from the first substantial unit on, up to ``max_chars``.

    Skips covers, title pages and empty navs; consecutive units are joined so short
    units (PDF pages) still give the analyzer a real sample of the book.
    """
    text, longest = "", ""
    for i in range(len(doc.units)):
        unit = doc.text(i).strip()
        if not text and len(unit) < ANALYSIS_MIN_CHARS:
            longest = max(longest, unit, key=len)
            continue
        text += unit + "\n\n"
        if len(text) >= max_chars:
            break
    return (text or longest)[:max_chars]


def lead_context_for(doc: Document, index: int, chunker: SmartChunker) -> str:
    """Last blocks of the previous unit: PDF sentences often continue on the next page."""
    if index == 0:
        return ""
    tail = doc.blocks(index - 1, chunker)[-chunker.overlap_blocks :]
    return "\n\n".join(b.text for b in tail)


def trail_context_for(doc: Document, index: int, chunker: SmartChunker) -> str:
    """First block of the next unit: tells a page ending mid-sentence how it goes on."""
    if index + 1 >= len(doc.units):
        return ""
    head = doc.blocks(index + 1, chunker)[:1]
    return head[0].text if head else ""


def unit_groups(todo: list[int], blocks: dict, chunker: SmartChunker) -> list[list[int]]:
    """Consecutive units translated together, up to the chunker's target size.

    PDF pages hold ~350 tokens: one call per page would spend as many tokens on the
    fixed instructions as on the text, and cut sentences at every page end. Grouped,
    a sentence crossing pages stays in one chunk; results are split back per unit.
    """
    groups: list[list[int]] = []
    size = 0
    for i in todo:
        tokens = sum(chunker.count_tokens(b.text) for b in blocks[i])
        if groups and groups[-1][-1] == i - 1 and size + tokens <= chunker.target_tokens:
            groups[-1].append(i)
            size += tokens
        else:
            groups.append([i])
            size = tokens
    return groups


async def translate_document(
    doc: Document,
    pipeline: TranslationPipeline,
    output_path: Path,
    *,
    previous: Translations | None = None,
    completed: Collection[int] = (),
    analysis: dict[str, Any] | None = None,
    max_concurrency: int = 1,
) -> AsyncGenerator[TranslationProgress, None]:
    previous = previous or {}
    units = doc.units
    total = len(units)

    # Phase 1: analysis
    if analysis:
        pipeline.book_summary = analysis.get("summary", "")
    else:
        text = analysis_text(doc)
        if text:
            try:
                analysis_call = asyncio.ensure_future(pipeline.analyze_chapter(text))
                stop = asyncio.ensure_future(pipeline.cancelled.wait())
                await asyncio.wait({analysis_call, stop}, return_when=asyncio.FIRST_COMPLETED)
                stop.cancel()
                if not analysis_call.done():  # paused during the analysis: abandon the call
                    analysis_call.cancel()
                    return
                result = analysis_call.result()
                pipeline.book_summary = result.summary
                yield TranslationProgress(
                    event_type="analysis_complete",
                    total_chapters=total,
                    message=f"Analysis complete: {result.genre}, {result.tone}",
                    data={
                        "analysis": result.model_dump(
                            include={"genre", "tone", "characters", "summary"}
                        ),
                    },
                )
            except Exception as e:
                yield TranslationProgress(
                    event_type="error", message=f"Analysis failed (continuing without): {e}"
                )

    # Phase 2: units
    results: Translations = {i: previous.get(i) for i in completed}
    for i in sorted(completed):
        yield TranslationProgress(
            event_type="chapter_skipped",
            chapter_index=i,
            total_chapters=total,
            message=f"Chapter {i + 1}/{total} already translated",
        )

    queue: asyncio.Queue[TranslationProgress | None] = asyncio.Queue()
    semaphore = asyncio.Semaphore(max(1, max_concurrency))
    chunker = pipeline.chunker
    blocks = {i: doc.blocks(i, chunker) for i in range(total) if i not in completed}

    def unit_checkpoint(i: int) -> list[str | None]:
        saved = previous.get(i)
        return list(saved) if saved and len(saved) == len(blocks[i]) else [None] * len(blocks[i])

    def per_unit(group: list[int], values: list) -> dict[int, list]:
        """Split a group's per-block list back into its units."""
        out, at = {}, 0
        for i in group:
            out[i] = values[at : at + len(blocks[i])]
            at += len(blocks[i])
        return out

    def split_checkpoint(group: list[int], event: TranslationProgress):
        """A chunk's checkpoint, per unit it covers (a chunk may span two pages)."""
        data, at = event.data, 0
        start, translations = data["offset"], data["translations"]
        end = start + (len(translations) if translations is not None else 0)
        for i in group:
            lo, hi = max(start, at), min(end, at + len(blocks[i]))
            if lo < hi or (translations is None and at <= start < at + len(blocks[i])):
                yield TranslationProgress(
                    event_type="chunk_done",
                    chapter_index=i,
                    total_chapters=total,
                    chunk_index=event.chunk_index,
                    total_chunks=event.total_chunks,
                    data={
                        "offset": lo - at,
                        "translations": (
                            None if translations is None else translations[lo - start : hi - start]
                        ),
                        "total_blocks": len(blocks[i]),
                    },
                )
            at += len(blocks[i])

    async def run(group: list[int]) -> None:
        first, last = group[0], group[-1]
        async with semaphore:
            if pipeline._cancelled:
                return
            try:
                translated: list[str | None] | None = None
                group_previous = [t for i in group for t in unit_checkpoint(i)]
                async for event in pipeline.translate_chapter(
                    [b for i in group for b in blocks[i]],
                    first,
                    total,
                    group_previous if any(t is not None for t in group_previous) else None,
                    lead_context=lead_context_for(doc, first, chunker),
                    trail_context=trail_context_for(doc, last, chunker),
                ):
                    if event.event_type == "chapter_done":
                        translated = event.data["translated_blocks"]
                    elif event.event_type == "chunk_done":
                        for part in split_checkpoint(group, event):
                            await queue.put(part)
                        continue
                    await queue.put(event)
                if pipeline._cancelled or translated is None:
                    return
                for i, translations in per_unit(group, translated).items():
                    results[i] = translations
                    await queue.put(
                        TranslationProgress(
                            event_type="chapter_saved",
                            chapter_index=i,
                            total_chapters=total,
                            message=f"Chapter {i + 1} saved",
                            data={
                                "item_id": units[i].item_id,
                                "order_index": i,
                                "translations": translations,
                                "failed_chunks": [0] if None in translations else [],
                                "translated_html": doc.render(i, translations),
                            },
                        )
                    )
            except Exception as e:
                await queue.put(
                    TranslationProgress(
                        event_type="error",
                        chapter_index=first,
                        total_chapters=total,
                        message=f"Chapter {first + 1} failed: {e}",
                    )
                )

    groups = unit_groups([i for i in range(total) if i not in completed], blocks, chunker)
    tasks = [asyncio.create_task(run(group)) for group in groups]

    async def close_when_done() -> None:
        await asyncio.gather(*tasks, return_exceptions=True)
        await queue.put(None)

    async def close_when_cancelled() -> None:
        # A pause must not wait for model calls in flight (minutes with a slow or
        # rate-limited model): end the loop now; finished chunks are already queued.
        await pipeline.cancelled.wait()
        await queue.put(None)

    closer = asyncio.create_task(close_when_done())
    stopper = asyncio.create_task(close_when_cancelled())
    try:
        while (event := await queue.get()) is not None:
            yield event
            if pipeline._cancelled:
                break
    finally:
        for task in [*tasks, closer, stopper]:
            task.cancel()

    if pipeline._cancelled:
        # Work finished before the stop is already queued: deliver its checkpoints.
        while not queue.empty():
            if (event := queue.get_nowait()) is not None:
                yield event
        return

    # Phase 3: output
    yield TranslationProgress(event_type="building_epub", message="Building translated file...")
    doc.save(output_path, results)
    failed_units = [
        i for i in range(total) if results.get(i) is None or None in (results.get(i) or [])
    ]
    yield TranslationProgress(
        event_type="job_complete",
        total_chapters=total,
        message="Translation completed"
        + (f" with {len(failed_units)} incomplete chapter(s)" if failed_units else " successfully"),
        data={
            "output_path": str(output_path),
            "filename": output_path.name,
            "failed_units": failed_units,
        },
    )
