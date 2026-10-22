from app.services.chunker import SmartChunker

HTML = "<html><body><h1>Title</h1><p>One.</p><p>Two.</p><h2>Sub</h2><p>Three.</p></body></html>"


def test_headings_start_new_chunks():
    chunks = SmartChunker().chunk_html(HTML)
    assert [c.text for c in chunks] == ["Title\n\nOne.\n\nTwo.", "Sub\n\nThree."]


def test_overlap_context_comes_from_previous_chunk():
    chunks = SmartChunker(overlap_blocks=1).chunk_html(HTML)
    assert chunks[0].context_text == ""
    assert chunks[1].context_text == "Two."


def test_chunking_is_deterministic():
    a = SmartChunker(target_tokens=2, max_tokens=4).chunk_html(HTML)
    b = SmartChunker(target_tokens=2, max_tokens=4).chunk_html(HTML)
    assert [c.text for c in a] == [c.text for c in b]
    assert len(a) > 2
