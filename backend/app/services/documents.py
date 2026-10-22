"""
Documents — format adapters behind a common interface.

A document is a list of *units* (EPUB: XHTML documents in manifest order; PDF:
pages), each split into translatable blocks. Translations are always handled as
one string (or None = keep original) per block of a unit, so the translation
flow, checkpoints and resume logic are format-agnostic. ``save`` writes the
output in the same format as the input, changing only the text.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import ebooklib
from ebooklib import epub

from app.services.chunker import SmartChunker, TextBlock
from app.services.html_processor import (
    extract_visible_text,
    normalize_epub_html,
    replace_text_blocks,
)

Translations = dict[int, list[str | None] | None]


@dataclass
class Unit:
    item_id: str
    title: str


class Document(ABC):
    format: str
    suffix: str
    media_type: str

    @property
    @abstractmethod
    def units(self) -> list[Unit]: ...

    @abstractmethod
    def blocks(self, index: int, chunker: SmartChunker) -> list[TextBlock]:
        """Translatable blocks of a unit, in a stable order."""

    @abstractmethod
    def text(self, index: int) -> str:
        """Plain visible text of a unit (analysis, previews)."""

    def render(self, index: int, translations: list[str | None] | None) -> str | None:
        """Translated unit for preview/storage, if the format has a textual form."""
        return None

    @abstractmethod
    def save(self, path: Path, translations: Translations) -> Path:
        """Write the translated document (same format as the input)."""

    @abstractmethod
    def info(self) -> dict:
        """Metadata: ``title`` and ``language`` (best effort)."""


class EpubDocument(Document):
    format = "epub"
    suffix = ".epub"
    media_type = "application/epub+zip"

    def __init__(self, path: str | Path):
        self.book = epub.read_epub(str(path))
        self._items = [i for i in self.book.get_items() if i.get_type() == ebooklib.ITEM_DOCUMENT]
        # Keep originals: save() mutates items, render() must always start from the source
        self._original = [item.get_content() for item in self._items]

    @property
    def units(self) -> list[Unit]:
        return [Unit(item_id=i.get_id(), title=i.get_name()) for i in self._items]

    def blocks(self, index: int, chunker: SmartChunker) -> list[TextBlock]:
        return chunker.extract_blocks(self._original[index])

    def text(self, index: int) -> str:
        return extract_visible_text(self._original[index])

    def _translated_content(self, index: int, translations: list[str | None] | None) -> bytes:
        if not translations or all(t is None for t in translations):
            return self._original[index]
        return normalize_epub_html(replace_text_blocks(self._original[index], translations))

    def render(self, index: int, translations: list[str | None] | None) -> str | None:
        return self._translated_content(index, translations).decode("utf-8", errors="replace")

    def save(self, path: Path, translations: Translations) -> Path:
        # Apply translated content in-place on the original book to preserve the
        # EPUB structure exactly (CSS, TOC, manifest, spine, spacing).
        for index, item in enumerate(self._items):
            item.set_content(self._translated_content(index, translations.get(index)))
        _ensure_toc_uids(self.book.toc)
        path.parent.mkdir(parents=True, exist_ok=True)
        epub.write_epub(str(path), self.book)
        return path

    def info(self) -> dict:
        title = self.book.get_metadata("DC", "title")
        language = self.book.get_metadata("DC", "language")
        return {
            "title": title[0][0] if title else "Unknown",
            "language": language[0][0] if language else "english",
        }


def open_document(path: str | Path) -> Document:
    suffix = Path(path).suffix.lower()
    if suffix == ".epub":
        return EpubDocument(path)
    if suffix == ".pdf":
        from app.services.pdf_service import PdfDocument

        return PdfDocument(path)
    raise ValueError(f"Unsupported document format: {suffix}")


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
