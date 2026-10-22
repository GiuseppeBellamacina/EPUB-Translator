"""
Translation Service — translate a whole document, resumable and concurrent.

Phases:
1. Analysis (skipped when resuming with a stored analysis): seeds the glossary.
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
from app.services.documents import Document, Translations

ANALYSIS_MIN_CHARS = 500


def _analysis_text(doc: Document) -> str:
    """First unit with substantial text (skips covers, title pages, empty navs)."""
    texts = [doc.text(i) for i in range(min(len(doc.units), 10))]
    return next((t for t in texts if len(t) >= ANALYSIS_MIN_CHARS), max(texts, key=len, default=""))


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
        text = _analysis_text(doc)
        if text:
            try:
                result = await pipeline.analyze_chapter(text)
                pipeline.book_summary = result.summary
                yield TranslationProgress(
                    event_type="analysis_complete",
                    total_chapters=total,
                    message=f"Analysis complete: {result.genre}, {result.tone}",
                    data={
                        "analysis": result.model_dump(
                            include={"genre", "tone", "characters", "summary"}
                        ),
                        "glossary": [e.model_dump() for e in pipeline.glossary.entries],
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

    async def run(i: int) -> None:
        async with semaphore:
            if pipeline._cancelled:
                return
            try:
                translations: list[str | None] | None = None
                failed: list[int] = []
                async for event in pipeline.translate_chapter(
                    doc.blocks(i, pipeline.chunker), i, total, previous.get(i)
                ):
                    if event.event_type == "chapter_done":
                        translations = event.data["translated_blocks"]
                        failed = event.data["failed_chunks"]
                    await queue.put(event)
                if pipeline._cancelled:
                    return
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
                            "failed_chunks": failed,
                            "translated_html": doc.render(i, translations),
                        },
                    )
                )
            except Exception as e:
                await queue.put(
                    TranslationProgress(
                        event_type="error",
                        chapter_index=i,
                        total_chapters=total,
                        message=f"Chapter {i + 1} failed: {e}",
                    )
                )

    tasks = [asyncio.create_task(run(i)) for i in range(total) if i not in completed]

    async def close_when_done() -> None:
        await asyncio.gather(*tasks, return_exceptions=True)
        await queue.put(None)

    closer = asyncio.create_task(close_when_done())
    try:
        while (event := await queue.get()) is not None:
            yield event
            if pipeline._cancelled:
                break
    finally:
        for task in [*tasks, closer]:
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
            "glossary": [e.model_dump() for e in pipeline.glossary.entries],
        },
    )
