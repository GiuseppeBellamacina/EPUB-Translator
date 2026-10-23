"""
Translation Service — translate a whole document, resumable and concurrent.

Phases:
1. Analysis (skipped when resuming with a stored analysis): seeds glossary and compendium.
2. Units (chapters/pages) run as concurrent tasks, at most ``max_concurrency`` at
   a time; their events are merged into one stream. Units already completed are
   skipped; partially translated units resume from their per-block checkpoint.
3. Doubt review: the passages the translator was unsure about (``doubt_flagged``, also
   added when a compendium gender is corrected) are revisited with the final glossary
   and compendium; corrections are applied before saving.
4. The output is written in the input format from all unit translations.

Every event is yielded to the caller, which persists checkpoints (``chunk_done``,
``chapter_saved``, ``doubt_flagged``, ``doubt_resolved``, ``analysis_complete``) as they
arrive.
"""

import asyncio
import re
from collections.abc import AsyncGenerator, Callable, Collection, Coroutine, Iterable
from pathlib import Path
from typing import Any

from app.agents.pipeline import TranslationPipeline, TranslationProgress
from app.agents.reviewer import resolve_doubts
from app.agents.translator_agent import keep_unfinished, split_paragraphs
from app.knowledge.glossary import replace_term, same_agreement
from app.knowledge.matcher import TermMatcher
from app.services import app_settings
from app.services.chunker import SmartChunker, TextBlock
from app.services.documents import Document, Translations

ANALYSIS_MIN_CHARS = 500
ANALYSIS_MAX_CHARS = 12000  # analyzer truncation (agents/analyzer.py)
_PLACEHOLDER = re.compile(r"</?\d+/?>")

Queue = asyncio.Queue[TranslationProgress | None]


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


def mention_doubts(
    names: list[str],
    translated: Translations,
    blocks_of: Callable[[int], list[TextBlock]],
    **doubt: Any,
) -> dict[int, list[dict]]:
    """The breadcrumbs back to an entry: the translated blocks whose source names it (any of
    ``names``: name and aliases, plurals and possessives folded), as doubts per unit.

    The source is the index: a matcher over a whole book takes milliseconds and is always
    current (aliases and entries learned later included), so nothing is stored per block.
    """
    matcher = TermMatcher()
    for name in names:
        matcher.add(name, 0)
    found: dict[int, list[dict]] = {}
    for unit, translations in sorted(translated.items()):
        for b, block in enumerate(blocks_of(unit)):
            if b < len(translations or []) and translations[b] is not None:
                if matcher.find(block.text):
                    found.setdefault(unit, []).append(
                        {"block": b, "source": block.text, "translation": translations[b], **doubt}
                    )
    return found


def doubt_keys(bookmarks: Iterable[dict]) -> dict[tuple[int, int], list[dict]]:
    """Doubts per (unit, block): quote, reason and, for a glossary change, old/new text."""
    keys: dict[tuple[int, int], list[dict]] = {}
    for b in bookmarks:
        doubt = {k: b.get(k) for k in ("quote", "reason", "old_text", "new_text")}
        if doubt not in (found := keys.setdefault((b["unit"], b["block"]), [])):
            found.append(doubt)
    return keys


def _line(doubt: dict) -> str:
    return f"{doubt['quote']}: {doubt['reason']}"


async def translate_document(
    doc: Document,
    pipeline: TranslationPipeline,
    output_path: Path,
    *,
    previous: Translations | None = None,
    completed: Collection[int] = (),
    analysis: dict[str, Any] | None = None,
    max_concurrency: int = 1,
    bookmarks: list[dict] | None = None,
) -> AsyncGenerator[TranslationProgress, None]:
    """``bookmarks``: the open doubts of earlier runs (``unit``, ``block``, ``quote``, ``reason``)."""
    previous = previous or {}
    units = doc.units
    total = len(units)

    # Phase 1: analysis
    if analysis:
        pipeline.book_summary = analysis.get("summary", "")
    elif pipeline.features.analysis:
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

    semaphore = asyncio.Semaphore(max(1, max_concurrency))
    chunker = pipeline.chunker
    blocks: dict[int, list[TextBlock]] = {
        i: doc.blocks(i, chunker) for i in range(total) if i not in completed
    }

    def unit_blocks(i: int) -> list[TextBlock]:
        if i not in blocks:  # a unit completed in an earlier run
            blocks[i] = doc.blocks(i, chunker)
        return blocks[i]

    def unit_checkpoint(i: int) -> list[str | None]:
        saved = previous.get(i)
        return list(saved) if saved and len(saved) == len(blocks[i]) else [None] * len(blocks[i])

    # what is translated so far, per block: auto-bookmarks go only to translated blocks
    done: Translations = {i: list(t) for i, t in previous.items() if t}
    doubts = doubt_keys(bookmarks or [])  # (unit, block) -> [{quote, reason, ...}]

    def locate(group: list[int], block: int) -> tuple[int, int]:
        """(unit, block in it) of a block of a group's concatenated blocks."""
        for i in group:
            if block < len(blocks[i]):
                return i, block
            block -= len(blocks[i])
        raise IndexError(block)

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
                part = None if translations is None else translations[lo - start : hi - start]
                if part is not None:
                    done.setdefault(i, [None] * len(blocks[i]))[lo - at : hi - at] = part
                yield TranslationProgress(
                    event_type="chunk_done",
                    chapter_index=i,
                    total_chapters=total,
                    chunk_index=event.chunk_index,
                    total_chunks=event.total_chunks,
                    data={"offset": lo - at, "translations": part, "total_blocks": len(blocks[i])},
                )
            at += len(blocks[i])

    def flagged(unit: int, found: list[dict]) -> TranslationProgress:
        return TranslationProgress(
            event_type="doubt_flagged",
            chapter_index=unit,
            total_chapters=total,
            message=f"{len(found)} doubt(s) bookmarked for the final review",
            data={"doubts": found},
        )

    def split_doubts(group: list[int], event: TranslationProgress):
        """A chunk's doubts, per unit (their block indexes are the group's)."""
        per: dict[int, list[dict]] = {}
        for doubt in event.data["doubts"]:
            unit, block = locate(group, doubt["block"])
            per.setdefault(unit, []).append({**doubt, "block": block})
        return [flagged(unit, found) for unit, found in per.items()]

    def corrected_mentions(names: list[str]) -> list[TranslationProgress]:
        """A compendium gender was corrected: bookmark the translated blocks naming it."""
        events = []
        for e in pipeline.compendium.entries:
            if e.name in names:
                reason = f"Compendium corrected: {e.name} is {e.gender}"
                found = mention_doubts(
                    [e.name, *e.aliases], done, unit_blocks, quote=e.name, reason=reason
                )
                events += [flagged(unit, doubts) for unit, doubts in found.items()]
        return events

    def saved(i: int, translations: list[str | None]) -> TranslationProgress:
        return TranslationProgress(
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

    async def run(group: list[int], queue: Queue) -> None:
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
                    elif event.event_type == "doubt_flagged":
                        for part in split_doubts(group, event):
                            await queue.put(part)
                        continue
                    await queue.put(event)
                    if event.event_type == "compendium_update" and event.data.get("corrected"):
                        for part in corrected_mentions(event.data["corrected"]):
                            await queue.put(part)
                if pipeline._cancelled or translated is None:
                    return
                for i, translations in per_unit(group, translated).items():
                    results[i] = translations
                    await queue.put(saved(i, translations))
            except Exception as e:
                await queue.put(
                    TranslationProgress(
                        event_type="error",
                        chapter_index=first,
                        total_chapters=total,
                        message=f"Chapter {first + 1} failed: {e}",
                    )
                )

    async def stream(
        jobs: Callable[[Queue], list[Coroutine]],
    ) -> AsyncGenerator[TranslationProgress, None]:
        """Run the coroutines (they put events on the queue) and yield their events.

        A pause ends the stream at once, without waiting for model calls in flight
        (minutes with a slow or rate-limited model); work finished before it is still
        delivered, so its checkpoints are saved.
        """
        queue: Queue = asyncio.Queue()
        tasks = [asyncio.create_task(job) for job in jobs(queue)]

        async def close_when_done() -> None:
            await asyncio.gather(*tasks, return_exceptions=True)
            await queue.put(None)

        async def close_when_cancelled() -> None:
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
            while not queue.empty():
                if (event := queue.get_nowait()) is not None:
                    yield event

    def remember(event: TranslationProgress) -> TranslationProgress:
        if event.event_type == "doubt_flagged":
            for key, found in doubt_keys(
                {"unit": event.chapter_index, **d} for d in event.data["doubts"]
            ).items():
                doubts.setdefault(key, []).extend(d for d in found if d not in doubts[key])
        return event

    groups = unit_groups([i for i in range(total) if i not in completed], blocks, chunker)
    async for event in stream(lambda queue: [run(group, queue) for group in groups]):
        yield remember(event)
    if pipeline._cancelled:
        return

    # Phase 3: doubt review, in rounds: bookmarks added meanwhile (an edit in the UI while
    # this runs) join the next round
    touched: set[int] = set()
    handled: dict[tuple[int, int], list[dict]] = {}
    f = pipeline.features

    def translated(key: tuple[int, int]) -> bool:
        unit, block = key
        return (results.get(unit) or [])[block : block + 1] not in ([], [None])

    def next_round() -> list[tuple[int, int]]:
        for key, found in doubt_keys(pipeline.added_bookmarks).items():
            doubts.setdefault(key, []).extend(d for d in found if d not in doubts[key])
        pipeline.added_bookmarks.clear()
        return [
            key
            for key, found in sorted(doubts.items())
            if translated(key) and any(d not in handled.get(key, []) for d in found)
        ]

    async def review(unit: int, block: int, queue: Queue) -> None:
        source = unit_blocks(unit)[block].text
        before = unit_blocks(unit)[block - 1].text if block else ""
        after = "\n\n".join(b.text for b in unit_blocks(unit)[block + 1 : block + 2])
        around = before + "\n" + after  # names said just before or after the passage
        current = results[unit][block]
        found = doubts[(unit, block)]
        # a glossary change: replace the old translation of the term where it occurs as is
        text = current
        for d in found:
            if d.get("old_text") and d.get("new_text"):
                text = replace_term(text, d["old_text"], d["new_text"])
        # without the model only when nothing around the term has to agree with it
        exact = text != current and all(
            d.get("old_text") and d.get("new_text") and same_agreement(d["old_text"], d["new_text"])
            for d in found
        )
        fixed, note = None, ""
        if exact:  # every change done without the model
            fixed = text
            note = "Replaced " + ", ".join(f"{d['old_text']} → {d['new_text']}" for d in found)
        else:
            limits = app_settings.load()
            async with semaphore:
                try:
                    resolution = await resolve_doubts(
                        pipeline.review_llm,
                        original_text=source,
                        # the original: given a replaced text, models tend to "confirm" it
                        # even where the words around the term no longer agree
                        translated_text=current,
                        doubts=sorted({_line(d) for d in found}),
                        glossary=(
                            pipeline.glossary.relevant(source, around, limits.glossary_limit)
                            if f.use_glossary
                            else []
                        ),
                        compendium=(
                            pipeline.compendium.relevant(source, around, limits.compendium_limit)
                            if f.use_compendium
                            else []
                        ),
                        source_language=pipeline.source_language,
                        target_language=pipeline.target_language,
                        style_instructions=pipeline.style_instructions,
                        previous=before,
                        following=after,
                    )
                except Exception as e:  # stays open: the next run retries it
                    await queue.put(
                        TranslationProgress(
                            event_type="error",
                            chapter_index=unit,
                            total_chapters=total,
                            message=f"Doubt review failed on chapter {unit + 1}: {e}",
                        )
                    )
                    return
            note = resolution.note.strip()
            answer = None
            if resolution.translation and resolution.translation.strip() != current:
                new = keep_unfinished(source, " ".join(split_paragraphs(resolution.translation)))
                if sorted(_PLACEHOLDER.findall(new)) == sorted(_PLACEHOLDER.findall(source)):
                    for d in found:  # an occurrence of the old term the model left
                        if d.get("old_text") and d.get("new_text"):
                            new = replace_term(new, d["old_text"], d["new_text"])
                    glossary = pipeline.glossary.relevant(source) if f.enforce_glossary else []
                    answer = pipeline.glossary.enforce(new, glossary)
                else:
                    note = "Kept: the correction lost inline markup. " + note
            if answer:
                fixed = answer
            elif text != current:  # the model changed nothing: at least the term is replaced
                fixed, note = text, "Replaced the term only (the model proposed no change)"
        if fixed:
            results[unit][block] = fixed
            touched.add(unit)
        await queue.put(
            TranslationProgress(
                event_type="doubt_resolved",
                chapter_index=unit,
                total_chapters=total,
                message=f"Doubt on chapter {unit + 1}: {'fixed' if fixed else 'kept'}",
                data={
                    "block": block,
                    "status": "fixed" if fixed else "kept",
                    "translation": fixed,
                    "note": note,
                },
            )
        )

    started = False
    while pipeline.doubt_review and (pending := next_round()):
        if not started:
            started = True
            yield TranslationProgress(
                event_type="doubt_review_start",
                total_chapters=total,
                message=f"Reviewing {len(pending)} passage(s) translated with doubts",
            )
        for key in pending:
            handled[key] = list(doubts[key])
        async for event in stream(lambda queue: [review(u, b, queue) for u, b in pending]):
            yield event
        if pipeline._cancelled:
            break
    # fixes made before a pause are saved too: their bookmarks are closed
    for unit in sorted(touched):
        yield saved(unit, results[unit])
    if pipeline._cancelled:
        return

    # Phase 4: output
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
