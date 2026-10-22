"""Generate a small sample EPUB (3 English chapters) for testing the pipeline.

Run inside the dev container:

    docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm backend \
        python scripts/make_sample_epub.py

The file is written to ``sample_books/sample_en.epub``. Tests import
``write_sample_epub`` to build the same book in a temp directory.
"""

from pathlib import Path

from ebooklib import epub

CHAPTERS = [
    (
        "Chapter 1: The Lighthouse",
        [
            "The old lighthouse stood at the edge of the cliff. Every night its lamp "
            "swept across the dark water, warning ships of the rocks below.",
            "Mara had lived there since she was a child. She knew every step of the "
            "spiral staircase and every creak of the ancient wooden door.",
            "Tonight the wind was stronger than usual. She climbed to the top and "
            "watched the storm gather on the horizon.",
        ],
    ),
    (
        "Chapter 2: The Letter",
        [
            "A letter arrived with the morning boat. It was sealed with red wax and "
            "carried no name, only a small drawing of a wave.",
            "Mara opened it carefully. Inside, a single sentence asked her to light "
            "the lamp three times before midnight.",
            "She did not understand the message, but something in her heart told her "
            "to obey. The sea had never lied to her before.",
        ],
    ),
    (
        "Chapter 3: The Signal",
        [
            "At midnight Mara lit the lamp three times, just as the letter had asked. "
            "The beam cut through the fog like a blade of gold.",
            "Far out on the water, a small light answered. One flash, then two, then "
            "three, perfectly matching her own.",
            "She smiled for the first time in years. Whoever was out there, she was "
            "no longer alone on the silent coast.",
        ],
    ),
]


def build_chapter(index: int, title: str, paragraphs: list[str]) -> epub.EpubHtml:
    file_name = f"chapter_{index}.xhtml"
    chapter = epub.EpubHtml(title=title, file_name=file_name, lang="en")
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    chapter.content = f"<html><head></head><body><h1>{title}</h1>{body}</body></html>"
    return chapter


def write_sample_epub(out_path: Path) -> Path:
    book = epub.EpubBook()
    book.set_identifier("sample-en-bau-miao-001")
    book.set_title("The Lighthouse Keeper")
    book.set_language("en")
    book.add_author("Test Author")

    chapters: list[epub.EpubHtml] = []
    for i, (title, paragraphs) in enumerate(CHAPTERS, start=1):
        chapter = build_chapter(i, title, paragraphs)
        book.add_item(chapter)
        chapters.append(chapter)

    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *chapters]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out_path), book)
    return out_path


def main() -> None:
    out_path = Path(__file__).resolve().parent.parent / "sample_books" / "sample_en.epub"
    print(f"Wrote {write_sample_epub(out_path)}")


if __name__ == "__main__":
    main()
