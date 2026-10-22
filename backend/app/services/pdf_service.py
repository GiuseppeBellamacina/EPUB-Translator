"""
PDF adapter — translate a PDF keeping its layout: same pages, images, vector
graphics, links and metadata; only the text changes.

Each page is a unit; its blocks are PyMuPDF text blocks. Spans whose style
differs from the block's dominant one (bold, italic, size: e.g. a drop cap) are
sent as numbered placeholders, like inline tags in EPUB.

On save, the original glyphs of every translated block are removed with
redactions that keep images and line art, then the translation is typeset in
the block's own rectangle with a metric-compatible font (Carlito for Calibri,
Liberation for Arial/Times/Courier...), shrinking only when the text would not
fit — nothing ever moves on the page.

shortcut: scanned PDFs (no text layer) are rejected rather than OCR'd; add an
OCR step (e.g. Tesseract via PyMuPDF) if they need supporting.
"""

import html
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from app.services.chunker import SmartChunker, TextBlock
from app.services.documents import Document, Translations, Unit

# Ligature-free copies made at image build (scripts/strip_ligatures.py); system fonts as
# fallback. Same file names in both: only one set may be in the archive.
STRIPPED_FONT_DIR = "/usr/local/share/fonts/pdf"
SYSTEM_FONT_DIRS = ["/usr/share/fonts/truetype/crosextra", "/usr/share/fonts/truetype/liberation"]

# family -> file stem; files are <stem>-Regular/Bold/Italic/BoldItalic.ttf
FONT_FILES = {
    "carlito": "Carlito",
    "caladea": "Caladea",
    "sans": "LiberationSans",
    "serif": "LiberationSerif",
    "mono": "LiberationMono",
}

_PLACEHOLDER = re.compile(r"<(/?)(\d+)(/?)>")
_FLAG_ITALIC, _FLAG_SERIF, _FLAG_MONO, _FLAG_BOLD = 2, 4, 8, 16
HEADING_RATIO = 1.3


class ScannedPdfError(ValueError):
    pass


@dataclass(frozen=True)
class Style:
    family: str
    size: float
    bold: bool
    italic: bool
    color: int


@dataclass
class PdfBlock:
    text: str  # with placeholders
    bbox: tuple[float, float, float, float]
    style: Style  # dominant style
    styles: dict[int, Style]  # placeholder id -> span style
    span_rects: list[tuple[float, float, float, float]]
    align: str = "left"
    line_height: float = 1.2
    indent: float = 0.0  # first-line indent (pt)
    heading: bool = False
    extra: dict = field(default_factory=dict)


def font_family(font_name: str, flags: int) -> str:
    name = font_name.split("+")[-1].lower()
    if "calibri" in name:
        return "carlito"
    if "cambria" in name:
        return "caladea"
    if flags & _FLAG_MONO or any(k in name for k in ("courier", "mono", "consol")):
        return "mono"
    if flags & _FLAG_SERIF or any(k in name for k in ("times", "serif", "georgia", "garamond")):
        return "serif"
    return "sans"


def _span_style(span: dict) -> Style:
    name, flags = span["font"], span["flags"]
    lowered = name.lower()
    return Style(
        family=font_family(name, flags),
        size=round(span["size"], 1),
        bold=bool(flags & _FLAG_BOLD) or "bold" in lowered or "black" in lowered,
        italic=bool(flags & _FLAG_ITALIC) or "italic" in lowered or "oblique" in lowered,
        color=span["color"],
    )


def _join_line(text: str, line: str) -> str:
    if not text:
        return line
    if text.endswith("-") and line[:1].islower():  # hyphenated word across lines
        return text[:-1] + line
    return text + ("" if text.endswith(" ") else " ") + line


def _alignment(lines: list[dict], bbox: tuple) -> str:
    if len(lines) < 2:
        return "left"
    x0, x1 = bbox[0], bbox[2]
    width = x1 - x0
    body = lines[:-1]
    full = sum(x1 - line["bbox"][2] < 0.03 * width for line in body)
    if full >= max(1, 0.7 * len(body)):  # tolerate a short drop-cap line
        return "justify"
    centers = [(line["bbox"][0] + line["bbox"][2]) / 2 for line in lines]
    if all(abs(c - (x0 + x1) / 2) < 2 for c in centers) and any(
        line["bbox"][0] - x0 > 4 for line in lines
    ):
        return "center"
    if all(abs(line["bbox"][2] - x1) < 2 for line in lines) and any(
        line["bbox"][0] - x0 > 4 for line in lines
    ):
        return "right"
    return "left"


_SENTENCE_END = re.compile(r"[.!?:;…\"”’»)\]]\s*$")


def _raw_blocks(page: pymupdf.Page) -> list[tuple[tuple, list[dict]]]:
    """(bbox, horizontal lines) of each text block, continuation blocks merged.

    Word processors often split one paragraph into several blocks (e.g. the line
    with a drop cap). A block is merged into the previous one when it sits right
    below it in the same column, the previous one does not end a sentence and it
    starts in lowercase: translating half sentences separately would be poor.
    """
    raw = page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
    merged: list[tuple[tuple, list[dict]]] = []
    for block in raw["blocks"]:
        if block.get("type") != 0 or not pymupdf.Rect(block["bbox"]).is_valid:
            continue
        lines = [ln for ln in block["lines"] if ln["dir"] == (1.0, 0.0) and ln["spans"]]
        text = "".join(s["text"] for ln in lines for s in ln["spans"]).strip()
        if not text:
            continue
        if merged:
            prev_bbox, prev_lines = merged[-1]
            prev_text = "".join(s["text"] for s in prev_lines[-1]["spans"]).strip()
            size = max(s["size"] for s in lines[0]["spans"])
            same_column = block["bbox"][0] < prev_bbox[2] and prev_bbox[0] < block["bbox"][2]
            close = 0 <= block["bbox"][1] - prev_bbox[3] < size
            if same_column and close and not _SENTENCE_END.search(prev_text) and text[0].islower():
                bbox = tuple(pymupdf.Rect(prev_bbox) | pymupdf.Rect(block["bbox"]))
                merged[-1] = (bbox, prev_lines + lines)
                continue
        merged.append((tuple(block["bbox"]), lines))
    return merged


def extract_page_blocks(page: pymupdf.Page) -> list[PdfBlock]:
    """Horizontal text blocks with letters, in reading order."""
    blocks: list[PdfBlock] = []
    for bbox, lines in _raw_blocks(page):
        block = {"bbox": bbox}
        spans = [s for ln in lines for s in ln["spans"] if s["text"].strip()]
        if not spans:
            continue

        weights = Counter()
        for s in spans:
            weights[_span_style(s)] += len(s["text"].strip())
        dominant = weights.most_common(1)[0][0]

        styles: dict[int, Style] = {}
        text, open_style = "", None
        for line in lines:
            line_text = ""
            for span in line["spans"]:
                style = _span_style(span)
                chunk = span["text"]
                if not chunk.strip():
                    line_text += chunk
                    continue
                if style != dominant and style != open_style:
                    if open_style is not None:
                        line_text += f"</{len(styles)}>"
                    styles[len(styles) + 1] = style
                    line_text += f"<{len(styles)}>"
                    open_style = style
                elif style == dominant and open_style is not None:
                    line_text += f"</{len(styles)}>"
                    open_style = None
                line_text += chunk
            text = _join_line(text, line_text.strip())
        if open_style is not None:
            text += f"</{len(styles)}>"
        text = re.sub(r"\s+", " ", text).strip()
        if not any(c.isalpha() for c in _PLACEHOLDER.sub("", text)):
            continue

        baselines = [ln["spans"][0]["origin"][1] for ln in lines]
        gaps = [b - a for a, b in zip(baselines, baselines[1:]) if b > a]
        line_height = (sum(gaps) / len(gaps) / dominant.size) if gaps else 1.2
        blocks.append(
            PdfBlock(
                text=text,
                bbox=tuple(block["bbox"]),
                style=dominant,
                styles=styles,
                span_rects=[tuple(s["bbox"]) for s in spans],
                align=_alignment(lines, block["bbox"]),
                line_height=min(max(line_height, 1.0), 2.0),
                indent=max(0.0, lines[0]["bbox"][0] - bbox[0]) if len(lines) > 1 else 0.0,
            )
        )

    sizes = Counter()
    for b in blocks:
        sizes[b.style.size] += len(b.text)
    body_size = sizes.most_common(1)[0][0] if sizes else 0
    for b in blocks:
        b.heading = bool(body_size) and b.style.size >= body_size * HEADING_RATIO
    return blocks


# --- Typesetting --------------------------------------------------------------


def _css_style(style: Style, factor: float = 1.0) -> str:
    return (
        f"font-family: {style.family}; font-size: {style.size * factor:.2f}px;"
        f" color: #{style.color:06x};"
        f" font-weight: {'bold' if style.bold else 'normal'};"
        f" font-style: {'italic' if style.italic else 'normal'};"
    )


def block_html(block: PdfBlock, translation: str, factor: float = 1.0) -> str:
    """Translation as HTML, placeholders turned back into styled spans."""
    out, stack, pos = [], [], 0
    for match in _PLACEHOLDER.finditer(translation):
        out.append(html.escape(translation[pos : match.start()]))
        pos = match.end()
        closing, n = match.group(1), int(match.group(2))
        if n not in block.styles or match.group(3):
            continue
        if not closing:
            out.append(f'<span style="{_css_style(block.styles[n], factor)}">')
            stack.append(n)
        elif stack and stack[-1] == n:
            out.append("</span>")
            stack.pop()
        else:  # unbalanced: plain text fallback
            return html.escape(_PLACEHOLDER.sub("", translation))
    out.append(html.escape(translation[pos:]))
    if stack:
        return html.escape(_PLACEHOLDER.sub("", translation))
    return "".join(out)


def _font_css() -> str:
    rules = []
    for family, stem in FONT_FILES.items():
        for weight, style, suffix in (
            ("normal", "normal", "Regular"),
            ("bold", "normal", "Bold"),
            ("normal", "italic", "Italic"),
            ("bold", "italic", "BoldItalic"),
        ):
            rules.append(
                f"@font-face {{font-family: {family}; font-weight: {weight};"
                f" font-style: {style}; src: url({stem}-{suffix}.ttf);}}"
            )
    return "\n".join(rules)


_FONT_CSS = _font_css() + "\n* {margin: 0; padding: 0;}"


def _archive() -> pymupdf.Archive:
    archive = pymupdf.Archive()
    folders = [STRIPPED_FONT_DIR] if Path(STRIPPED_FONT_DIR).is_dir() else SYSTEM_FONT_DIRS
    for folder in folders:
        if Path(folder).is_dir():
            archive.add(folder)
    return archive


GAP_USE = 0.6  # share of the free space below a region its text may grow into


def _obstacles(page: pymupdf.Page, blocks: list[PdfBlock]) -> list[pymupdf.Rect]:
    rects = [pymupdf.Rect(b.bbox) for b in blocks]
    rects += [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()]
    rects += [pymupdf.Rect(d["rect"]) for d in page.get_drawings()]
    return rects


def _regions(
    blocks: list[PdfBlock], translations: list[str | None], obstacles: list[pymupdf.Rect]
) -> list[list[int]]:
    """Group consecutive translated paragraphs that flow together.

    Same column, same font, close vertically and nothing (image, drawing, other
    block) in between. A region is typeset as one flow, so its paragraphs share
    one font scale and spacing, as in the original.
    """
    regions: list[list[int]] = []
    for i, (block, translation) in enumerate(zip(blocks, translations)):
        if translation is None:
            continue
        if regions and regions[-1][-1] == i - 1:
            prev = blocks[i - 1]
            a, b = pymupdf.Rect(prev.bbox), pymupdf.Rect(block.bbox)
            overlap = min(a.x1, b.x1) - max(a.x0, b.x0)
            gap = pymupdf.Rect(a.x0, a.y1, a.x1, b.y0)
            if (
                overlap >= 0.8 * min(a.width, b.width)
                and prev.style.size == block.style.size
                and prev.style.family == block.style.family
                and 0 <= b.y0 - a.y1 < 2.5 * block.style.size
                and not any(o.intersects(gap) for o in obstacles if o not in (a, b))
            ):
                regions[-1].append(i)
                continue
        regions.append([i])
    return regions


def _region_box(
    page: pymupdf.Page, members: list[PdfBlock], obstacles: list[pymupdf.Rect]
) -> pymupdf.Rect:
    """Union of the paragraphs, extended down into part of the free space below.

    Only space free of other text, images and drawings is used, so the page
    composition does not change; it lets translations (often longer) keep their size.
    """
    box = pymupdf.Rect(members[0].bbox)
    for m in members[1:]:
        box |= pymupdf.Rect(m.bbox)
    own = [pymupdf.Rect(m.bbox) for m in members]
    limit = page.rect.y1 - 36  # keep clear of the bottom margin
    for other in obstacles:
        if other in own:
            continue
        if other.x0 < box.x1 and box.x0 < other.x1 and other.y0 >= box.y1 - 0.5:
            limit = min(limit, other.y0)
    box.y1 += max(0.0, (limit - box.y1) * GAP_USE)
    box.x1 += 1  # rounding slack so a line that fitted originally still fits
    return box


def region_html(
    members: list[PdfBlock], translations: list[str], box: pymupdf.Rect, factor: float = 1.0
) -> str:
    """One <p> per paragraph with its original spacing, indents and style (scaled by factor)."""
    paragraphs, prev_bottom = [], None
    for block, translation in zip(members, translations):
        top = 0.0 if prev_bottom is None else max(0.0, block.bbox[1] - prev_bottom)
        prev_bottom = block.bbox[3]
        style = (
            f"{_css_style(block.style, factor)} text-align: {block.align};"
            f" line-height: {block.line_height:.2f}; text-indent: {block.indent * factor:.1f}px;"
            f" margin-top: {top * factor:.1f}px; margin-left: {block.bbox[0] - box.x0:.1f}px;"
            f" margin-right: {max(0.0, box.x1 - 1 - block.bbox[2]):.1f}px;"
        )
        paragraphs.append(f'<p style="{style}">{block_html(block, translation, factor)}</p>')
    return "".join(paragraphs)


def typeset(page: pymupdf.Page, blocks: list[PdfBlock], translations: list[str | None]) -> None:
    """Replace the text of translated blocks in place."""
    if all(t is None for t in translations):
        return
    obstacles = _obstacles(page, blocks)
    regions = _regions(blocks, translations, obstacles)
    boxes = [_region_box(page, [blocks[i] for i in r], obstacles) for r in regions]

    for i, translation in enumerate(translations):
        if translation is not None:
            for rect in blocks[i].span_rects:
                page.add_redact_annot(rect, fill=False)
    page.apply_redactions(
        images=pymupdf.PDF_REDACT_IMAGE_NONE,
        graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
        text=pymupdf.PDF_REDACT_TEXT_REMOVE,
    )

    archive = _archive()
    htmls = [
        lambda f, r=r, box=box: region_html(
            [blocks[i] for i in r], [translations[i] for i in r], box, f
        )
        for r, box in zip(regions, boxes)
    ]
    factors = _page_factors(page, regions, blocks, boxes, htmls, archive)
    for html_for, box, factor in zip(htmls, boxes, factors):
        page.insert_htmlbox(box, html_for(factor), css=_FONT_CSS, archive=archive)


def _page_factors(page, regions, blocks, boxes, htmls, archive) -> list[float]:
    """One scale per font size across the page's regions, so text of the same kind
    (e.g. body paragraphs split by a scene break) never ends up in different sizes."""
    scratch = pymupdf.open()
    probe = scratch.new_page(width=page.rect.width, height=page.rect.height)
    needed = [
        probe.insert_htmlbox(box, html_for(1.0), css=_FONT_CSS, archive=archive)[1]
        for html_for, box in zip(htmls, boxes)
    ]
    scratch.close()
    per_size: dict[float, float] = {}
    for region, scale in zip(regions, needed):
        size = blocks[region[0]].style.size
        per_size[size] = min(per_size.get(size, 1.0), scale)
    return [per_size[blocks[r[0]].style.size] for r in regions]


# --- Document adapter ---------------------------------------------------------


class PdfDocument(Document):
    format = "pdf"
    suffix = ".pdf"
    media_type = "application/pdf"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.pdf = pymupdf.open(self.path)
        self._blocks: dict[int, list[PdfBlock]] = {}
        if not any(page.get_text("text").strip() for page in self.pdf):
            raise ScannedPdfError("The PDF has no text layer (scanned?): OCR is not supported")

    def page_blocks(self, index: int) -> list[PdfBlock]:
        if index not in self._blocks:
            self._blocks[index] = extract_page_blocks(self.pdf[index])
        return self._blocks[index]

    @property
    def units(self) -> list[Unit]:
        return [Unit(item_id=f"page-{i + 1}", title=f"Page {i + 1}") for i in range(len(self.pdf))]

    def blocks(self, index: int, chunker: SmartChunker) -> list[TextBlock]:
        return [
            chunker.make_block("h2" if b.heading else "p", b.text) for b in self.page_blocks(index)
        ]

    def text(self, index: int) -> str:
        return self.pdf[index].get_text("text")

    def render(self, index: int, translations: list[str | None] | None) -> str | None:
        blocks = self.page_blocks(index)
        translations = translations or [None] * len(blocks)
        paragraphs = [
            html.escape(_PLACEHOLDER.sub("", t if t is not None else b.text))
            for b, t in zip(blocks, translations)
        ]
        return "<html><body>" + "".join(f"<p>{p}</p>" for p in paragraphs) + "</body></html>"

    def save(self, path: Path, translations: Translations) -> Path:
        out = pymupdf.open(self.path)  # fresh copy: keeps metadata, outline, links
        for index, page_translations in translations.items():
            if page_translations:
                typeset(out[index], self.page_blocks(index), page_translations)
        path.parent.mkdir(parents=True, exist_ok=True)
        out.save(path, garbage=3, deflate=True)
        out.close()
        return path

    def info(self) -> dict:
        meta = self.pdf.metadata or {}
        return {"title": meta.get("title") or self.path.stem, "language": "english"}
