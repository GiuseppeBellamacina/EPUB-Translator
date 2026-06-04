"""
Smart Chunker — Hybrid paragraph + sliding window chunking for EPUB HTML.

Strategy:
1. Parse HTML into structural blocks (paragraphs, headings, divs)
2. Merge small blocks until reaching token target (~500-800 tokens per chunk)
3. Add overlap context from previous chunk (marked as context, not to translate)
4. Respect boundaries: never split mid-sentence or mid-tag
5. Headings always start a new chunk
"""

from dataclasses import dataclass, field

import tiktoken
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCK_TAGS = {"p", "div", "blockquote", "li", "td", "th", "figcaption", "dt", "dd"}
SKIP_TAGS = {"script", "style", "meta", "link", "noscript"}
STRUCTURAL_TAGS = HEADING_TAGS | BLOCK_TAGS

# Approximate tokens per character ratio for English text
CHARS_PER_TOKEN = 4


@dataclass
class TextBlock:
    """A structural block of text extracted from HTML."""

    tag_name: str
    text: str
    html: str
    element: Tag | None = None
    is_heading: bool = False
    token_count: int = 0


@dataclass
class Chunk:
    """A translation chunk with optional overlap context."""

    blocks: list[TextBlock] = field(default_factory=list)
    context_blocks: list[TextBlock] = field(default_factory=list)  # From previous chunk

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)

    @property
    def context_text(self) -> str:
        return "\n\n".join(b.text for b in self.context_blocks)

    @property
    def total_tokens(self) -> int:
        return sum(b.token_count for b in self.blocks)


class SmartChunker:
    """
    Hybrid chunker that respects HTML structure and provides context overlap.

    Args:
        target_tokens: Target token count per chunk (default 600)
        max_tokens: Maximum token count before forcing a split (default 1000)
        overlap_blocks: Number of blocks from previous chunk to include as context (default 2)
        use_tiktoken: Whether to use tiktoken for accurate counting (slower)
    """

    def __init__(
        self,
        target_tokens: int = 600,
        max_tokens: int = 1000,
        overlap_blocks: int = 2,
        use_tiktoken: bool = False,
    ):
        self.target_tokens = target_tokens
        self.max_tokens = max_tokens
        self.overlap_blocks = overlap_blocks
        self._encoder = None
        if use_tiktoken:
            try:
                self._encoder = tiktoken.get_encoding("cl100k_base")
            except Exception:
                pass

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        if self._encoder:
            return len(self._encoder.encode(text))
        # Fast approximation
        return max(1, len(text) // CHARS_PER_TOKEN)

    def extract_blocks(self, html_content: str | bytes) -> list[TextBlock]:
        """Extract structural text blocks from HTML content."""
        if isinstance(html_content, bytes):
            html_content = html_content.decode("utf-8", errors="replace")

        soup = BeautifulSoup(html_content, "html.parser")
        blocks: list[TextBlock] = []

        # Find body, or use whole document
        body = soup.find("body") or soup

        self._extract_from_element(body, blocks)
        return blocks

    def _extract_from_element(self, element: Tag, blocks: list[TextBlock]):
        """Recursively extract text blocks from an element."""
        for child in element.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                text = child.strip()
                if text:
                    blocks.append(
                        TextBlock(
                            tag_name="text",
                            text=text,
                            html=str(child),
                            element=None,
                            is_heading=False,
                            token_count=self.count_tokens(text),
                        )
                    )
                continue
            if not isinstance(child, Tag):
                continue

            tag_name = child.name.lower() if child.name else ""

            if tag_name in SKIP_TAGS:
                continue

            if tag_name in STRUCTURAL_TAGS:
                text = child.get_text(separator=" ", strip=True)
                if text:
                    blocks.append(
                        TextBlock(
                            tag_name=tag_name,
                            text=text,
                            html=str(child),
                            element=child,
                            is_heading=tag_name in HEADING_TAGS,
                            token_count=self.count_tokens(text),
                        )
                    )
            else:
                # Recurse into non-block elements (span, a, em, etc. at top level)
                self._extract_from_element(child, blocks)

    def create_chunks(self, blocks: list[TextBlock]) -> list[Chunk]:
        """
        Group blocks into chunks respecting:
        - Token limits (target_tokens soft, max_tokens hard)
        - Headings always start new chunks
        - Sliding window overlap for context
        """
        if not blocks:
            return []

        chunks: list[Chunk] = []
        current_blocks: list[TextBlock] = []
        current_tokens = 0

        for block in blocks:
            # Heading always starts a new chunk
            if block.is_heading and current_blocks:
                chunks.append(self._build_chunk(current_blocks, chunks))
                current_blocks = []
                current_tokens = 0

            # Would exceed max? Flush first
            if current_tokens + block.token_count > self.max_tokens and current_blocks:
                chunks.append(self._build_chunk(current_blocks, chunks))
                current_blocks = []
                current_tokens = 0

            current_blocks.append(block)
            current_tokens += block.token_count

            # Reached target? Flush if at a natural boundary
            if current_tokens >= self.target_tokens:
                chunks.append(self._build_chunk(current_blocks, chunks))
                current_blocks = []
                current_tokens = 0

        # Remaining blocks
        if current_blocks:
            chunks.append(self._build_chunk(current_blocks, chunks))

        return chunks

    def _build_chunk(self, blocks: list[TextBlock], previous_chunks: list[Chunk]) -> Chunk:
        """Build a chunk with overlap context from previous chunks."""
        context_blocks: list[TextBlock] = []

        if previous_chunks and self.overlap_blocks > 0:
            # Get last N blocks from previous chunk as context
            prev_blocks = previous_chunks[-1].blocks
            context_blocks = prev_blocks[-self.overlap_blocks :]

        return Chunk(blocks=list(blocks), context_blocks=context_blocks)

    def chunk_html(self, html_content: str | bytes) -> list[Chunk]:
        """Main entry point: extract blocks and create chunks from HTML."""
        blocks = self.extract_blocks(html_content)
        return self.create_chunks(blocks)
