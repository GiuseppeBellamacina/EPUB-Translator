"""
HTML Processor — block extraction and reconstruction for EPUB translation.

Extraction and reconstruction share ``extract_html_blocks`` so block indexes are
identical on both sides: translation ``i`` always lands on block ``i``.

A block is either a leaf structural element (``<p>``, ``<h1>``, ``<li>``... with no
nested structural element carrying text) or a *run* of consecutive inline nodes
(bare text, ``<span>``, ``<em>``...) inside a container that also holds blocks.

Inline markup is sent to the model as numbered placeholders — ``<1>bold</1>``,
``<2/>`` for void/empty tags — and the original tags (with their attributes) are
restored from the translation. Unbalanced placeholders fall back to plain text.
"""

import copy
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag

# Tags whose content should never be modified
SKIP_TAGS = {"script", "style", "meta", "link", "noscript", "pre"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCK_TAGS = {"p", "div", "blockquote", "li", "td", "th", "figcaption", "dt", "dd"}
STRUCTURAL_TAGS = HEADING_TAGS | BLOCK_TAGS

_PLACEHOLDER = re.compile(r"<(/?)(\d+)(/?)>")


@dataclass
class HtmlBlock:
    """A translatable unit of an HTML document."""

    text: str  # visible text with inline placeholders
    nodes: list  # DOM nodes the block replaces (one Tag, or a run of inline nodes)
    tags: dict[int, Tag] = field(default_factory=dict)  # placeholder id -> original tag
    tag_name: str = "text"

    @property
    def is_heading(self) -> bool:
        return self.tag_name in HEADING_TAGS


def parse_html(html_content: str | bytes) -> tuple[BeautifulSoup, str, str]:
    """Parse HTML, splitting off the XML declaration and DOCTYPE (re-added on output)."""
    if isinstance(html_content, bytes):
        html_content = html_content.decode("utf-8", errors="replace")

    xml_declaration = ""
    doctype = ""
    xml_match = re.match(r"\s*(<\?xml[^?]*\?>)\s*", html_content)
    if xml_match:
        xml_declaration = xml_match.group(1)
        html_content = html_content[xml_match.end() :]
    doctype_match = re.match(r"(<!DOCTYPE[^>]*>)\s*", html_content, re.IGNORECASE)
    if doctype_match:
        doctype = doctype_match.group(1)
        html_content = html_content[doctype_match.end() :]

    return BeautifulSoup(html_content, "html.parser"), xml_declaration, doctype


def extract_visible_text(html_content: str | bytes) -> str:
    """Extract all visible text from HTML for analysis purposes."""
    soup, _, _ = parse_html(html_content)
    for tag in soup.find_all(SKIP_TAGS):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


# --- Extraction ---------------------------------------------------------------


def _has_text(node) -> bool:
    if type(node) is NavigableString:
        return bool(node.strip())
    return isinstance(node, Tag) and node.name not in SKIP_TAGS and bool(node.get_text(strip=True))


def _is_container(tag: Tag) -> bool:
    """A tag holding structural descendants with text: recurse instead of taking it whole."""
    return any(_has_text(d) for d in tag.find_all(STRUCTURAL_TAGS))


def _is_translatable(text: str) -> bool:
    return any(c.isalpha() for c in _PLACEHOLDER.sub("", text))


def extract_html_blocks(soup: BeautifulSoup) -> list[HtmlBlock]:
    """Translatable blocks of a parsed document, in document order."""
    blocks: list[HtmlBlock] = []
    _walk(soup.find("body") or soup, blocks)
    return blocks


def _walk(container: Tag, blocks: list[HtmlBlock]) -> None:
    run: list = []

    def flush() -> None:
        if run:
            _add_block(blocks, list(run), "text")
            run.clear()

    for child in list(container.children):
        if isinstance(child, Tag):
            if child.name in SKIP_TAGS:
                flush()
            elif child.name in STRUCTURAL_TAGS or _is_container(child):
                flush()
                if _is_container(child):
                    _walk(child, blocks)
                else:
                    _add_block(blocks, [child], child.name)
            else:
                run.append(child)
        elif type(child) is NavigableString:
            run.append(child)
        # Comments, doctypes, processing instructions are left alone
    flush()


def _add_block(blocks: list[HtmlBlock], nodes: list, tag_name: str) -> None:
    content = nodes[0].contents if tag_name != "text" else nodes
    text, tags = encode_inline(content)
    if _is_translatable(text):
        blocks.append(HtmlBlock(text=text, nodes=nodes, tags=tags, tag_name=tag_name))


def encode_inline(nodes: list) -> tuple[str, dict[int, Tag]]:
    """Serialize inline content as text with numbered placeholders for tags."""
    parts: list[str] = []
    tags: dict[int, Tag] = {}

    def walk(node) -> None:
        if type(node) is NavigableString:
            parts.append(str(node))
        elif isinstance(node, Tag):
            n = len(tags) + 1
            tags[n] = node
            if node.name in SKIP_TAGS or not node.get_text(strip=True):
                parts.append(f"<{n}/>")
            else:
                parts.append(f"<{n}>")
                for child in node.children:
                    walk(child)
                parts.append(f"</{n}>")

    for node in nodes:
        walk(node)
    return re.sub(r"\s+", " ", "".join(parts)).strip(), tags


# --- Reconstruction -----------------------------------------------------------


def _shell(tag: Tag) -> Tag:
    shell = copy.copy(tag)
    shell.clear()
    return shell


def restore_inline(text: str, tags: dict[int, Tag]) -> list | None:
    """Rebuild DOM nodes from placeholder text. None if placeholders are unbalanced."""
    root = Tag(name="root")
    stack: list[tuple[int | None, Tag]] = [(None, root)]
    pos = 0
    for match in _PLACEHOLDER.finditer(text):
        if match.start() > pos:
            stack[-1][1].append(NavigableString(text[pos : match.start()]))
        pos = match.end()
        closing, n, self_closing = match.group(1), int(match.group(2)), match.group(3)
        if n not in tags:
            continue  # invented placeholder: drop it
        if self_closing:
            stack[-1][1].append(copy.copy(tags[n]))
        elif not closing:
            element = _shell(tags[n])
            stack[-1][1].append(element)
            stack.append((n, element))
        elif stack[-1][0] == n:
            stack.pop()
        else:
            return None
    if pos < len(text):
        stack[-1][1].append(NavigableString(text[pos:]))
    if len(stack) != 1:
        return None
    return list(root.contents)


def _apply(block: HtmlBlock, translation: str) -> None:
    nodes = restore_inline(translation, block.tags)
    if nodes is None:
        nodes = [NavigableString(_PLACEHOLDER.sub("", translation))]

    if block.tag_name != "text":
        element = block.nodes[0]
        element.clear()
        for node in nodes:
            element.append(node)
        return

    first = block.nodes[0]
    for node in nodes:
        first.insert_before(node)
    for node in block.nodes:
        node.extract()


def replace_text_blocks(html_content: str | bytes, translations: Sequence[str | None]) -> bytes:
    """Write per-block translations back into the HTML, preserving structure.

    ``translations[i]`` replaces block ``i`` of ``extract_html_blocks``; ``None``
    (or a missing entry) leaves that block untouched.
    """
    soup, xml_declaration, doctype = parse_html(html_content)
    for block, translation in zip(extract_html_blocks(soup), translations):
        if translation is not None:
            _apply(block, translation)
    return _reconstruct_html(soup, xml_declaration, doctype).encode("utf-8")


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
