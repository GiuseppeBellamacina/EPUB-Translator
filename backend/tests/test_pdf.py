from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.agents.pipeline import TranslationPipeline
from app.core.fake_llm import _extract_source_text
from app.models.schemas import TranslationResult
from app.services.documents import open_document
from app.services.pdf_service import PdfBlock, ScannedPdfError, Style, block_html
from tests.conftest import translate

PARAGRAPH = (
    "The old lighthouse stood at the edge of the cliff. Every night its lamp swept across "
    "the dark water, warning <b>ships</b> of the rocks below."
)


@pytest.fixture
def sample_pdf(tmp_path):
    doc = pymupdf.open()
    for n in (1, 2):
        page = doc.new_page()
        page.insert_htmlbox(
            pymupdf.Rect(72, 72, 520, 110), f"<h1>Chapter {n}</h1>", css="h1 {font-size: 20px;}"
        )
        page.insert_htmlbox(
            pymupdf.Rect(72, 120, 520, 260),
            PARAGRAPH,
            css="* {font-size: 12px; font-family: serif;}",
        )
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), False)
        pix.set_rect(pix.irect, (200, 0, 0))
        page.insert_image(pymupdf.Rect(72, 300, 172, 400), pixmap=pix)
        page.draw_rect(pymupdf.Rect(300, 300, 400, 400), color=(0, 0, 1))
    path = tmp_path / "sample.pdf"
    doc.save(path)
    return path


def upper(prompt, n):
    return TranslationResult(translated_text=_extract_source_text(prompt).upper())


def test_extraction_keeps_inline_bold_as_placeholder(sample_pdf):
    doc = open_document(sample_pdf)
    blocks = doc.page_blocks(0)
    assert [b.heading for b in blocks] == [True, False]
    assert blocks[0].text == "Chapter 1"
    assert "warning <1>ships</1> of the rocks below." in blocks[1].text
    assert blocks[1].styles[1].bold and not blocks[1].style.bold


async def test_translated_pdf_keeps_layout_and_replaces_text(llm, sample_pdf):
    llm.handlers[TranslationResult] = upper
    events = await translate(sample_pdf, TranslationPipeline(llm=llm, enable_review=False))
    assert events[-1].event_type == "job_complete" and events[-1].data["failed_units"] == []

    src, out = pymupdf.open(sample_pdf), pymupdf.open(events[-1].data["output_path"])
    assert out.page_count == src.page_count
    for before, after in zip(src, out):
        assert after.rect == before.rect
        assert len(after.get_image_info()) == len(before.get_image_info()) == 1
        assert len(after.get_drawings()) == len(before.get_drawings())
        text = after.get_text()
        assert "lighthouse" not in text  # original glyphs removed
        assert "LIGHTHOUSE" in text and "CHAPTER" in text
        # inline bold survived: the translated word is set in a bold font
        bold = [
            s["text"]
            for b in after.get_text("dict")["blocks"]
            if b["type"] == 0
            for line in b["lines"]
            for s in line["spans"]
            if s["flags"] & 16
        ]
        assert any("SHIPS" in t for t in bold)
    # substitute fonts are subset, not embedded whole (Liberation Serif alone is ~400 KB)
    assert Path(events[-1].data["output_path"]).stat().st_size < 150_000


def test_continuation_blocks_are_merged(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "This sentence is split by the word processor and", fontsize=12)
    page.insert_text((72, 115), "continues in a separate block.", fontsize=12)
    path = tmp_path / "split.pdf"
    doc.save(path)
    blocks = open_document(path).page_blocks(0)
    assert [b.text for b in blocks] == [
        "This sentence is split by the word processor and continues in a separate block."
    ]


def test_unbalanced_placeholders_fall_back_to_plain_text():
    style = Style("sans", 12, False, False, 0)
    block = PdfBlock(
        "a <1>b</1>", (0, 0, 10, 10), style, {1: Style("sans", 12, True, False, 0)}, []
    )
    assert block_html(block, "x <1>y</1> & z") == (
        'x <span style="font-family: sans; font-size: 12.00px; color: #000000; '
        'font-weight: bold; font-style: normal;">y</span> &amp; z'
    )
    assert block_html(block, "x <1>y z") == "x y z"


def test_scanned_pdf_is_rejected(tmp_path, db):
    doc = pymupdf.open()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10), False)
    doc.new_page().insert_image(pymupdf.Rect(0, 0, 100, 100), pixmap=pix)
    path = tmp_path / "scan.pdf"
    doc.save(path)
    with pytest.raises(ScannedPdfError):
        open_document(path)

    from app.main import app

    with TestClient(app) as client, open(path, "rb") as f:
        response = client.post("/api/upload", files={"file": ("scan.pdf", f)})
    assert response.status_code == 400 and "no text layer" in response.json()["detail"]


def test_pdf_upload_translate_download(db, sample_pdf):
    from app.main import app

    with TestClient(app) as client:
        provider = client.post("/api/providers", json={"name": "f", "provider_type": "fake"}).json()
        with open(sample_pdf, "rb") as f:
            book = client.post("/api/upload", files={"file": ("sample.pdf", f)}).json()
        assert book["total_chapters"] == 2
        with client.websocket_connect(f"/ws/translate/{book['id']}") as ws:
            ws.send_json({"action": "start", "provider_id": provider["id"]})
            while (msg := ws.receive_json())["event"] not in ("job_complete", "error"):
                pass
        assert msg["event"] == "job_complete"
        preview = client.get(f"/api/books/{book['id']}/preview", params={"chapter_index": 1})
        assert "BAU" in preview.json()["translated_text"]
        download = client.get(f"/api/books/{book['id']}/download")
        assert download.headers["content-type"] == "application/pdf"
        assert download.content.startswith(b"%PDF")


async def test_short_pages_are_translated_together_and_saved_per_page(llm, tmp_path):
    doc = pymupdf.open()
    lines = ["The keeper climbed the stairs", "and lit the lamp before", "the storm came."]
    for line in lines:  # one sentence across three short pages
        doc.new_page().insert_htmlbox(pymupdf.Rect(72, 72, 520, 140), f"<p>{line}</p>")
    path = tmp_path / "pages.pdf"
    doc.save(path)

    llm.handlers[TranslationResult] = upper
    events = await translate(path, TranslationPipeline(llm=llm, enable_review=False))

    assert len(llm.calls_for(TranslationResult)) == 1  # one call for the three pages
    checkpoints = [e for e in events if e.event_type == "chunk_done"]
    assert [(e.chapter_index, e.data["offset"], e.data["total_blocks"]) for e in checkpoints] == [
        (0, 0, 1),
        (1, 0, 1),
        (2, 0, 1),
    ]
    saved = {
        e.chapter_index: e.data["translations"] for e in events if e.event_type == "chapter_saved"
    }
    assert saved == {i: [line.upper()] for i, line in enumerate(lines)}
    out = pymupdf.open(events[-1].data["output_path"])
    assert [" ".join(page.get_text().split()) for page in out] == [line.upper() for line in lines]
