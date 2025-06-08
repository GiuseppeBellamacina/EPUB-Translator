from ebooklib import epub, ITEM_DOCUMENT, ITEM_NAVIGATION
from bs4 import BeautifulSoup
from bs4.element import Comment
from tqdm.notebook import tqdm
from translator import Translator
from buffer import TextBuffer
from typing import Callable, Optional


def is_file_in_book(book: epub.EpubBook, filename: str) -> bool:
    return any(item.file_name == filename for item in book.get_items())


def dummy_translate_text(text):
    return "[DUMMY]" + text


def translate_with_translator(
    text: str, translator: Translator
) -> Optional[str]:
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


def compare_nav(book: epub.EpubBook, translated_book: epub.EpubBook) -> bool:
    """
    Compare the navigation (NAV) files of the original and translated books.
    Prints the NAV file names and checks if they are equal.
    Returns True if NAV file names are the same, False otherwise.
    """
    print("Comparing NAV files...\n")

    original_nav_files = sorted(
        item.file_name for item in book.get_items_of_type(ITEM_NAVIGATION)
    )
    translated_nav_files = sorted(
        item.file_name for item in translated_book.get_items_of_type(ITEM_NAVIGATION)
    )

    print("Original NAV:")
    for fname in original_nav_files:
        print(f"- {fname}")
    print("\nTranslated NAV:")
    for fname in translated_nav_files:
        print(f"- {fname}")
    are_equal = original_nav_files == translated_nav_files
    if are_equal:
        print("\n✅ The NAV files are equal.")
    else:
        print("\n❌ The NAV files are different.")
    return are_equal


def check_duplicated_items(book: epub.EpubBook) -> bool:
    """
    Check for duplicated items in the epub book.
    Prints duplicated file names if found.
    Returns True if there are duplicates, False otherwise.
    """
    seen = set()
    duplicates = set()
    print("Checking for duplicated items...\n")
    for item in book.get_items():
        if item.file_name in seen:
            print(f"❌ Duplicate found: {item.file_name}")
            duplicates.add(item.file_name)
        else:
            seen.add(item.file_name)
    if duplicates:
        print(f"\nTotal duplicates found: {len(duplicates)}")
        return False
    else:
        print("✅ No duplicated items found.")
        return True


def check_items_errors(book: epub.EpubBook) -> bool:
    """
    Check for errors in the items of the epub book.
    Prints error messages if any issues are found.
    Returns True if there are errors, False otherwise.
    """
    errors = False
    err_tag = "\33[1;31m[ERROR]\33[0m"
    print("Checking items for errors...\n")

    for item in book.get_items():
        if item.get_type() == ITEM_DOCUMENT:
            content = item.get_content()
            # 1) Check for empty content

            if not content or (
                isinstance(content, (bytes, str)) and not content.strip()
            ):
                print(f"{err_tag} Empty item: {item.file_name}")
                print(f"Content: {repr(content)}")
                errors = True
                continue
            # 2) Try parsing the content

            try:
                # Decode bytes if needed

                if isinstance(content, bytes):
                    content_decoded = content.decode("utf-8", errors="replace")
                else:
                    content_decoded = content
                # Must contain at least <html> ... </html>

                soup = BeautifulSoup(content_decoded, "html.parser")
                html_tag = soup.find("html")
                if html_tag is None:
                    print(f"{err_tag} Missing <html> tag in: {item.file_name}")
                    errors = True
                else:
                    # Optionally, check for <body>

                    if soup.find("body") is None:
                        print(f"[WARNING] Missing <body> tag in: {item.file_name}")
            except Exception as e:
                print(f"{err_tag} Failed to parse {item.file_name}: {e}")
                errors = True
    if errors:
        print("❌ Errors found: please fix the above items before writing the EPUB.")
    else:
        print("✅ All HTML documents appear valid.")
    return errors


def check_number_of_items(book: epub.EpubBook, translated_book: epub.EpubBook) -> bool:
    """
    Check if the number of items in the epub book matches the expected count.
    Prints a message indicating whether the counts match.
    Returns True if the counts match, False otherwise.
    """
    actual_count = get_number_of_items(book)
    translated_count = get_number_of_items(translated_book)

    print(f"Original book has {actual_count} items.")
    print(f"Translated book has {translated_count} items.")

    if actual_count == translated_count:
        print(
            "✅ The number of items matches between the original and translated books."
        )
        return True
    else:
        print(
            "❌ The number of items does not match between the original and translated books."
        )
        return False


def check_book(book: epub.EpubBook, translated_book: epub.EpubBook) -> bool:
    """
    Check the epub book for various issues, including NAV file check if translated_book is provided.
    Returns True if there are no issues, False otherwise.
    """
    print("Checking the EPUB book...\n")
    print("- " * 40)
    num_items_match = check_number_of_items(book, translated_book)
    print("-" * 40)
    nav_match = compare_nav(book, translated_book)
    print("-" * 40)
    has_duplicates = check_duplicated_items(book)
    print("-" * 40)
    has_errors = check_items_errors(book)
    print("-" * 40)
    print("EPUB book check completed.\n")

    if not (num_items_match and nav_match and has_duplicates and not has_errors):
        print("❌ The EPUB book has issues. Please fix them before proceeding.")
        return False
    else:
        print("✅ The EPUB book is valid and ready for writing.")
        return True
