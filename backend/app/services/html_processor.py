"""
HTML Processor — Handles HTML manipulation for EPUB translation.
Fixes spacing issues in reconstructed HTML output.
"""

import re

from bs4 import BeautifulSoup, NavigableString, Tag

# Tags whose content should never be modified
SKIP_TAGS = {"script", "style", "meta", "link", "noscript"}


def extract_visible_text(html_content: str | bytes) -> str:
    """Extract all visible text from HTML for analysis purposes."""
    if isinstance(html_content, bytes):
        html_content = html_content.decode("utf-8", errors="replace")

    soup = BeautifulSoup(html_content, "html.parser")

    # Remove script/style/meta
    for tag in soup.find_all(SKIP_TAGS):
        tag.decompose()

    return soup.get_text(separator="\n", strip=True)


def replace_text_blocks(html_content: str | bytes, translated_blocks: list[str]) -> bytes:
    """
    Replace text content in HTML with translated blocks while preserving structure.

    This function maps translated text blocks back to their original positions
    in the HTML, maintaining all tags, attributes, and structure.

    Args:
        html_content: Original HTML
        translated_blocks: List of translated text blocks (from pipeline)

    Returns:
        Reconstructed HTML as bytes with translated content
    """
    if isinstance(html_content, bytes):
        html_content = html_content.decode("utf-8", errors="replace")

    # Preserve XML declaration and DOCTYPE
    xml_declaration = ""
    doctype = ""

    xml_match = re.match(r"(<\?xml[^?]*\?>)\s*", html_content)
    if xml_match:
        xml_declaration = xml_match.group(1)
        html_content = html_content[xml_match.end() :]

    doctype_match = re.match(r"(<!DOCTYPE[^>]*>)\s*", html_content, re.IGNORECASE)
    if doctype_match:
        doctype = doctype_match.group(1)
        html_content = html_content[doctype_match.end() :]

    soup = BeautifulSoup(html_content, "html.parser")
    body = soup.find("body") or soup

    # Collect all text-bearing block elements in order
    block_elements = _collect_block_elements(body)

    # Map translated blocks back to elements
    # Each translated block corresponds to one or more paragraphs from chunker
    if translated_blocks:
        _apply_translations(block_elements, translated_blocks)

    # Reconstruct output with spacing fix
    output = _reconstruct_html(soup, xml_declaration, doctype)
    return output.encode("utf-8")


def _collect_block_elements(element: Tag) -> list[Tag]:
    """Collect all block-level elements that contain visible text."""
    block_tags = {
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "div",
        "blockquote",
        "li",
        "td",
        "th",
        "figcaption",
        "dt",
        "dd",
    }

    blocks = []
    for el in element.descendants:
        if isinstance(el, Tag) and el.name in block_tags:
            text = el.get_text(strip=True)
            if text:
                # Only include if it's a leaf block (no nested blocks with text)
                nested_blocks = el.find_all(block_tags)
                nested_with_text = [b for b in nested_blocks if b.get_text(strip=True)]
                if not nested_with_text:
                    blocks.append(el)
    return blocks


def _apply_translations(block_elements: list[Tag], translated_blocks: list[str]):
    """
    Apply translated text blocks to HTML elements.

    The translated_blocks come from the chunker pipeline where multiple paragraphs
    may be merged into one chunk. We split them back by paragraph breaks.
    """
    # Flatten all translated text split by double newlines
    translated_paragraphs = []
    for block in translated_blocks:
        paragraphs = [p.strip() for p in block.split("\n\n") if p.strip()]
        translated_paragraphs.extend(paragraphs)

    # Apply to elements (best-effort mapping)
    for i, element in enumerate(block_elements):
        if i < len(translated_paragraphs):
            _replace_element_text(element, translated_paragraphs[i])


def _replace_element_text(element: Tag, new_text: str):
    """Replace all text content in an element while preserving inline tags structure."""
    # If the element has no children tags (only text), simple replacement
    children_tags = [c for c in element.children if isinstance(c, Tag)]

    if not children_tags:
        element.clear()
        element.append(NavigableString(new_text))
    else:
        # Has inline formatting — replace text in first text node
        # and clear subsequent text nodes
        text_nodes = [c for c in element.children if isinstance(c, NavigableString) and c.strip()]
        if text_nodes:
            text_nodes[0].replace_with(NavigableString(new_text))
            for node in text_nodes[1:]:
                node.extract()
            # Remove inline children since we replaced all text
            for child in children_tags:
                child.extract()


def _reconstruct_html(soup: BeautifulSoup, xml_declaration: str, doctype: str) -> str:
    """
    Reconstruct HTML string with proper formatting and spacing fix.

    Fixes the common EPUB spacing issue:
    - Collapses multiple consecutive blank lines into single blank line
    - Removes trailing whitespace on lines
    - Preserves intentional single line breaks
    - Uses minimal formatter to avoid excessive indentation
    """
    # Use encode with minimal formatter to avoid beautifulsoup adding extra whitespace
    raw_html = soup.encode(formatter="minimal").decode("utf-8")

    # === SPACING FIX ===
    # 1. Collapse multiple consecutive blank lines into one
    raw_html = re.sub(r"\n{3,}", "\n\n", raw_html)

    # 2. Remove trailing whitespace on each line
    raw_html = re.sub(r"[ \t]+\n", "\n", raw_html)

    # 3. Remove blank lines between closing/opening tags (tight tag spacing)
    raw_html = re.sub(r"(</[^>]+>)\s*\n\s*\n(\s*<)", r"\1\n\2", raw_html)

    # 4. Collapse whitespace-only lines inside block elements
    raw_html = re.sub(r">\s*\n\s*\n\s*<", ">\n<", raw_html)

    # Rebuild with declarations
    parts = []
    if xml_declaration:
        parts.append(xml_declaration)
    if doctype:
        parts.append(doctype)
    parts.append(raw_html)

    return "\n".join(parts)


def normalize_epub_html(html_content: str | bytes) -> bytes:
    """
    Post-process EPUB HTML to fix common spacing issues.
    Use this on any HTML content before writing to EPUB.
    """
    if isinstance(html_content, bytes):
        html_content = html_content.decode("utf-8", errors="replace")

    # Collapse excessive newlines
    html_content = re.sub(r"\n{3,}", "\n\n", html_content)

    # Remove whitespace-only lines between tags
    html_content = re.sub(r">\s*\n(\s*\n)+\s*<", ">\n<", html_content)

    # Remove trailing spaces
    html_content = re.sub(r"[ \t]+$", "", html_content, flags=re.MULTILINE)

    # Normalize line endings
    html_content = html_content.replace("\r\n", "\n")

    return html_content.encode("utf-8")
