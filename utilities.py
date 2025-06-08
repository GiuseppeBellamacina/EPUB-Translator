from typing import Callable
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
from bs4.element import Comment
from tqdm.notebook import tqdm
from buffer import TextBuffer



def is_file_in_book(book: epub.EpubBook, filename: str) -> bool:
    return any(item.file_name == filename for item in book.get_items())


def translate_visible_text(
    html_content: bytes, translate_text_func: Callable, debug=False, **translate_kwargs
) -> bytes:
    xml_decl = ""
    doctype_decl = ""
    rest = html_content

    rest = rest.tobytes() if isinstance(rest, memoryview) else rest
    rest = rest.decode("utf-8")

    if rest.lstrip().startswith("<?xml"):
        xml_decl, rest = rest.lstrip().split("?>", 1)
        xml_decl += "?>\n"
        rest = rest.lstrip()
    if rest.lstrip().startswith("<!DOCTYPE"):
        doctype_decl, rest = rest.lstrip().split(">", 1)
        doctype_decl += ">\n"
        rest = rest.lstrip()
    soup = BeautifulSoup(rest, "html.parser")
    invisible_parents = {"style", "script", "head", "meta", "[document]"}

    buffer = TextBuffer(
        translate_func=lambda text: translate_text_func(text, **translate_kwargs),
        debug=debug,
    )

    for tag in soup.find_all(string=True):
        if (
            tag.parent
            and tag.parent.name not in invisible_parents
            and not isinstance(tag, Comment)
            and isinstance(tag, str)
            and tag.strip()
        ):
            buffer.add(tag, str(tag))
    buffer.flush()

    final_html = xml_decl + doctype_decl + str(soup)
    return final_html.encode("utf-8")


def replace_toc_items(toc: list, translated_items: dict) -> list:
    new_toc = []
    for entry in toc:
        if isinstance(entry, epub.Link):
            href = entry.href
            if href in translated_items:
                new_toc.append(
                    epub.Link(translated_items[href].file_name, entry.title, entry.uid)
                )
            else:
                new_toc.append(entry)
        elif isinstance(entry, tuple) and len(entry) == 2:
            link, subitems = entry
            new_subitems = replace_toc_items(subitems, translated_items)
            if link.href in translated_items:
                new_link = epub.Link(
                    translated_items[link.href].file_name, link.title, link.uid
                )
            else:
                new_link = link
            new_toc.append((new_link, new_subitems))
        else:
            new_toc.append(entry)
    return new_toc


def move_metadata(book: epub.EpubBook, new_book: epub.EpubBook) -> None:
    """
    Move metadata from the original book to the new book.
    Args:
        book (epub.EpubBook): The original epub book.
        new_book (epub.EpubBook): The new epub book to which metadata will be moved.
    """
    if book.get_metadata("DC", "identifier"):
        new_book.set_identifier(book.get_metadata("DC", "identifier")[0][0])
    if book.get_metadata("DC", "title"):
        new_book.set_title(book.get_metadata("DC", "title")[0][0])
    new_book.set_language("it")


def get_number_of_items(book: epub.EpubBook) -> int:
    """
    Get the number of items in the epub book.
    Args:
        book (epub.EpubBook): The epub book to check.
    Returns:
        int: The number of items in the book.
    """
    return len(list(book.get_items()))


def translate_and_add_items(
    book: epub.EpubBook,
    translated_book: epub.EpubBook,
    translate_text: Callable,
    debug=False,
    **translate_kwargs,
) -> dict:
    translated_items = {}
    num_items = get_number_of_items(book)
    for item in tqdm(book.get_items(), desc="Translating", total=num_items):
        if item.get_type() == ITEM_DOCUMENT:
            html = translate_visible_text(
                item.content, translate_text, debug=debug, **translate_kwargs
            )
            new_item = epub.EpubHtml(
                uid=item.get_id(),
                file_name=item.file_name,
                media_type=item.media_type,
                content=html,
            )
            translated_book.add_item(new_item)
            translated_items[item.get_id()] = new_item
        else:
            translated_book.add_item(item)
    return translated_items


def set_translated_toc(
    book: epub.EpubBook, translated_book: epub.EpubBook, translated_items: dict
) -> None:
    if book.toc:
        translated_book.toc = replace_toc_items(book.toc, translated_items)


def set_translated_spine(
    book: epub.EpubBook, translated_book: epub.EpubBook, translated_items: dict
) -> None:
    new_spine = []
    for entry in book.spine:
        orig_id = entry[0] if isinstance(entry, tuple) else entry
        new_spine.append(
            translated_items[orig_id].get_id()
            if orig_id in translated_items
            else orig_id
        )
    translated_book.spine = new_spine


def add_cover(book: epub.EpubBook, translated_book: epub.EpubBook) -> None:
    cover_item = book.get_item_with_id("cover")
    if cover_item and not is_file_in_book(translated_book, cover_item.file_name):
        translated_book.add_item(cover_item)
        translated_book.set_cover(cover_item.file_name, cover_item.get_content())


def add_ncx(translated_book: epub.EpubBook) -> None:
    if not is_file_in_book(translated_book, "toc.ncx"):
        translated_book.add_item(epub.EpubNcx())
