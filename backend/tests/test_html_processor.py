from bs4 import BeautifulSoup

from app.agents.translator_agent import translate_blocks
from app.models.schemas import TranslationResult
from app.services.chunker import SmartChunker
from app.services.html_processor import (
    encode_inline,
    extract_html_blocks,
    parse_html,
    replace_text_blocks,
    restore_inline,
)

# Nested containers, bare text and inline markup: the cases that used to misalign.
HTML = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html><head><title>T</title><style>p {}</style></head><body>
<h1>Title</h1>
<div class="wrap">Loose intro <em>text</em>
  <p>First <a href="#n1" class="x">link</a> here.</p>
  <div><p>Nested one.</p><p>Nested two.</p></div>
</div>
<p>Line<br/>break.</p>
<p>* * *</p>
<p><img src="a.png"/></p>
</body></html>"""


def _texts(html):
    soup, _, _ = parse_html(html)
    return [b.text for b in extract_html_blocks(soup)]


def test_extraction_finds_leaf_blocks_and_runs():
    assert _texts(HTML) == [
        "Title",
        "Loose intro <1>text</1>",
        "First <1>link</1> here.",
        "Nested one.",
        "Nested two.",
        "Line<1/>break.",
    ]


def test_chunker_and_reconstruction_share_block_order():
    chunk_texts = [b.text for c in SmartChunker().chunk_html(HTML) for b in c.blocks]
    assert chunk_texts == _texts(HTML)


def test_round_trip_preserves_tags_attributes_and_declarations():
    translations = [t.upper() for t in _texts(HTML)]  # placeholders are digits: unaffected
    out = replace_text_blocks(HTML, translations).decode()
    assert out.startswith('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>')
    soup = BeautifulSoup(out, "html.parser")
    link = soup.find("a")
    assert link.get_text() == "LINK" and link["href"] == "#n1" and link["class"] == ["x"]
    assert soup.find("em").get_text() == "TEXT"
    assert soup.find("br") is not None and soup.find("img")["src"] == "a.png"
    assert "NESTED TWO." in out and "* * *" in out and "p {}" in out
    assert _texts(out) == translations  # re-extraction is stable


def test_none_translation_leaves_block_untouched():
    out = replace_text_blocks(HTML, [None, None, "Primo <1>link</1> qui."]).decode()
    assert "Title" in out and "Loose intro" in out and "Primo" in out and "Nested one." in out


def test_restore_rejects_unbalanced_and_drops_unknown_placeholders():
    _, tags = encode_inline(BeautifulSoup("<p>a <b>b</b></p>", "html.parser").p.contents)
    assert restore_inline("a <1>b", tags) is None
    nodes = restore_inline("a <9>b</9> <1>c</1>", tags)
    assert "".join(str(n) for n in nodes) == "a b <b>c</b>"


def test_unbalanced_translation_falls_back_to_plain_text():
    html = "<p>a <b>b</b> c</p>"
    out = replace_text_blocks(html, ["x <1>y z"]).decode()
    assert "<p>x y z</p>" in out


async def test_merged_paragraphs_fall_back_to_per_block_translation(llm):
    # The model keeps merging the chunk into one paragraph; single blocks work.
    def merge(text, n):
        body = text.split("TRANSLATE the following", 1)[1].split("\n\n", 1)[1]
        return TranslationResult(translated_text=body.replace("\n\n", " ").upper())

    llm.handlers[TranslationResult] = merge
    kwargs = dict(
        context="", chapter_summary="", glossary=[], source_language="en", target_language="it"
    )
    out, *_ = await translate_blocks(llm, ["one", "two", "three"], **kwargs)
    assert out == ["ONE", "TWO", "THREE"]
    assert len(llm.calls_for(TranslationResult)) == 2 + 3  # 2 chunk attempts + 3 singles
