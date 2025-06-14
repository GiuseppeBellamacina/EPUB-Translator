from ebooklib import epub, ITEM_DOCUMENT, ITEM_NAVIGATION
from bs4 import BeautifulSoup
from utilities import get_number_of_items


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
    print("-" * 40)
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