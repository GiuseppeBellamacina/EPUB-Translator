from typing import Callable, List
from ebooklib import epub
from translator import Translator
from utilities import (
    move_metadata,
    translate_and_add_items,
    set_translated_toc,
    set_translated_spine,
    add_cover,
    add_ncx,
)


def dummy_translate_text(text):
    return "[DUMMY]" + text


def translate_with_translator(
    text: List[str], translator: Translator
) -> List[str]:
    if not translator:
        raise ValueError("Translator instance is required for translation.")
    if not isinstance(translator, Translator):
        raise TypeError("Expected a Translator instance for translation.")
    """
    Translate text using the provided Translator instance.
    Args:
        text (str): The text to translate.
        translator (Translator): The Translator instance to use.
    Returns:
        Optional[str]: The translated text or None if translation fails.
    """
    return translator.translate(text)


def translate_book(
    book: epub.EpubBook, translate_text: Callable, debug=False, **translate_kwargs
) -> epub.EpubBook:
    """
    Translate the visible text of all ITEM_DOCUMENT items in the given EPUB book.
    Returns a new EpubBook with translated content and preserved structure.
    """
    translated_book = epub.EpubBook()
    move_metadata(book, translated_book)
    translated_items = translate_and_add_items(
        book, translated_book, translate_text, debug, **translate_kwargs
    )
    set_translated_toc(book, translated_book, translated_items)
    set_translated_spine(book, translated_book, translated_items)
    add_cover(book, translated_book)
    add_ncx(translated_book)

    return translated_book
