"""
EPUB Service — High-level EPUB manipulation: load, translate, reconstruct, validate.
"""

import os
from pathlib import Path
from typing import AsyncGenerator

import ebooklib
from ebooklib import epub

from app.agents.pipeline import TranslationPipeline, TranslationProgress
from app.core.config import settings
from app.models.schemas import GlossaryItem
from app.services.html_processor import (
    extract_visible_text,
    normalize_epub_html,
    replace_text_blocks,
)


class EpubService:
    """Service for EPUB file operations."""

    @staticmethod
    def load_book(filepath: str | Path) -> epub.EpubBook:
        """Load an EPUB file."""
        return epub.read_epub(str(filepath))

    @staticmethod
    def save_book(book: epub.EpubBook, filepath: str | Path):
        """Save an EPUB file."""
        epub.write_epub(str(filepath), book)

    @staticmethod
    def get_book_info(book: epub.EpubBook) -> dict:
        """Extract book metadata."""
        title = book.get_metadata("DC", "title")
        language = book.get_metadata("DC", "language")
        creator = book.get_metadata("DC", "creator")

        # Count document items
        doc_items = [item for item in book.get_items() if item.get_type() == ebooklib.ITEM_DOCUMENT]

        return {
            "title": title[0][0] if title else "Unknown",
            "language": language[0][0] if language else "Unknown",
            "author": creator[0][0] if creator else "Unknown",
            "total_chapters": len(doc_items),
        }

    @staticmethod
    def get_chapters(book: epub.EpubBook) -> list[dict]:
        """Get list of chapters with their IDs and titles."""
        chapters = []
        for i, item in enumerate(book.get_items()):
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                content = item.get_content()
                text = extract_visible_text(content)
                title = item.get_name() or f"Chapter {i+1}"
                chapters.append(
                    {
                        "index": len(chapters),
                        "item_id": item.get_id(),
                        "title": title,
                        "text_preview": text[:200] + "..." if len(text) > 200 else text,
                        "text_length": len(text),
                    }
                )
        return chapters

    @staticmethod
    async def translate_book(
        book: epub.EpubBook,
        pipeline: TranslationPipeline,
        glossary: list[GlossaryItem] | None = None,
    ) -> AsyncGenerator[TranslationProgress, None]:
        """
        Translate an entire EPUB book using the agentic pipeline.

        Yields progress events for real-time UI updates.
        """
        if glossary:
            pipeline.set_glossary(glossary)

        # Collect document items
        doc_items = [item for item in book.get_items() if item.get_type() == ebooklib.ITEM_DOCUMENT]
        total_chapters = len(doc_items)

        # Phase 1: Analyze first chapter to build initial glossary
        if doc_items:
            first_text = extract_visible_text(doc_items[0].get_content())
            if first_text:
                try:
                    analysis = await pipeline.analyze_chapter(first_text)
                    pipeline.book_summary = analysis.summary
                    yield TranslationProgress(
                        event_type="analysis_complete",
                        message=f"Analysis complete: {analysis.genre}, {analysis.tone}",
                        data={
                            "analysis": {
                                "genre": analysis.genre,
                                "tone": analysis.tone,
                                "characters": analysis.characters,
                                "summary": analysis.summary,
                            },
                            "glossary": [e.model_dump() for e in pipeline.glossary],
                        },
                    )
                except Exception as e:
                    yield TranslationProgress(
                        event_type="error",
                        message=f"Analysis failed (continuing without): {str(e)}",
                    )

        # Phase 2: Translate each chapter
        translated_items: dict[str, bytes] = {}

        for i, item in enumerate(doc_items):
            if pipeline._cancelled:
                break

            content = item.get_content()

            # Translate chapter through pipeline
            translated_blocks: list[str] = []
            async for progress in pipeline.translate_chapter(
                content, i, total_chapters, pipeline.book_summary
            ):
                if progress.event_type == "chapter_done":
                    translated_blocks = progress.data.get("translated_blocks", [])
                yield progress

            # Reconstruct HTML with translations
            if translated_blocks:
                translated_html = replace_text_blocks(content, translated_blocks)
                translated_html = normalize_epub_html(translated_html)
                translated_items[item.get_id()] = translated_html
            else:
                translated_items[item.get_id()] = content

            # Emit per-chapter result so the caller can persist it (preview/DB)
            yield TranslationProgress(
                event_type="chapter_saved",
                chapter_index=i,
                total_chapters=total_chapters,
                message=f"Chapter {i + 1} saved",
                data={
                    "item_id": item.get_id(),
                    "order_index": i,
                    "translated_html": translated_items[item.get_id()].decode(
                        "utf-8", errors="replace"
                    ),
                },
            )

        # Phase 3: Build translated EPUB
        yield TranslationProgress(
            event_type="building_epub",
            message="Building translated EPUB file...",
        )

        # Apply translated content in-place on the original book to preserve
        # the EPUB structure exactly (CSS, TOC, manifest, spine, spacing).
        for item in doc_items:
            item_id = item.get_id()
            if item_id in translated_items:
                item.set_content(translated_items[item_id])

        _ensure_toc_uids(book.toc)

        # Save translated file
        output_filename = f"translated_{os.path.basename(book.title or 'book')}.epub"
        output_path = settings.translated_dir / output_filename
        EpubService.save_book(book, output_path)

        yield TranslationProgress(
            event_type="job_complete",
            message="Translation completed successfully",
            data={
                "output_path": str(output_path),
                "filename": output_filename,
                "glossary": [e.model_dump() for e in pipeline.glossary],
            },
        )


def _ensure_toc_uids(toc, _counter: list[int] | None = None) -> None:
    """Assign a uid to any TOC entry missing one.

    ebooklib raises a TypeError while writing the NCX when a TOC item's ``uid``
    is ``None`` (a known issue when re-saving a book read from disk). Walk the
    TOC tree and backfill missing uids so ``write_epub`` succeeds.
    """
    if _counter is None:
        _counter = [0]
    for entry in toc:
        if isinstance(entry, (tuple, list)):
            section, children = entry[0], entry[1]
            if hasattr(section, "uid") and getattr(section, "uid", None) is None:
                section.uid = f"toc_{_counter[0]}"
                _counter[0] += 1
            _ensure_toc_uids(children, _counter)
        else:
            if hasattr(entry, "uid") and getattr(entry, "uid", None) is None:
                entry.uid = f"toc_{_counter[0]}"
                _counter[0] += 1
