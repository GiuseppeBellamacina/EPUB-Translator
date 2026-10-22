"""
EPUB Service — EPUB metadata helpers used at upload time.

Translation and reconstruction live in ``documents.EpubDocument``.
"""

from pathlib import Path

import ebooklib
from ebooklib import epub

from app.services.html_processor import extract_visible_text


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
