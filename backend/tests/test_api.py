import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(db):
    with TestClient(app) as c:
        yield c


def _upload(client, sample_epub):
    provider = client.post("/api/providers", json={"name": "fake", "provider_type": "fake"}).json()
    with open(sample_epub, "rb") as f:
        book = client.post("/api/upload", files={"file": ("sample.epub", f)}).json()
    return provider, book


def _run(client, book_id, provider_id, stop_on=None, **start):
    events = []
    with client.websocket_connect(f"/ws/translate/{book_id}") as ws:
        ws.send_json({"action": "start", "provider_id": provider_id, **start})
        while True:
            msg = ws.receive_json()
            events.append(msg)
            if msg["event"] == stop_on:
                ws.send_json({"action": "stop"})
                stop_on = None
            if msg["event"] in ("job_complete", "cancelled", "error"):
                return events


def test_stop_pauses_and_start_resumes(client, sample_epub, monkeypatch):
    from tests.conftest import ScriptedLLM

    monkeypatch.setattr("app.jobs.runner.create_llm", lambda cfg: ScriptedLLM(delay=0.05))
    provider, book = _upload(client, sample_epub)

    events = _run(client, book["id"], provider["id"], stop_on="chunk_done")
    assert events[-1]["event"] == "cancelled"
    assert client.get(f"/api/books/{book['id']}").json()["status"] == "paused"

    events = _run(client, book["id"], provider["id"])
    assert "resuming" in events[0]["message"]
    assert events[-1]["event"] == "job_complete"
    assert client.get(f"/api/books/{book['id']}").json()["status"] == "completed"


def test_upload_translate_download(client, sample_epub):
    provider = client.post(
        "/api/providers",
        json={"name": "fake", "provider_type": "fake", "default_model": "fake-meow"},
    ).json()

    with open(sample_epub, "rb") as f:
        book = client.post("/api/upload", files={"file": ("sample.epub", f)}).json()
    assert book["status"] == "uploaded"

    with client.websocket_connect(f"/ws/translate/{book['id']}") as ws:
        ws.send_json({"action": "start", "provider_id": provider["id"]})
        events = []
        while True:
            msg = ws.receive_json()
            events.append(msg.get("event"))
            if msg.get("event") in ("job_complete", "error") or "error" in msg:
                break
    assert events[-1] == "job_complete"

    assert client.get(f"/api/books/{book['id']}").json()["status"] == "completed"
    preview = client.get(f"/api/books/{book['id']}/preview", params={"chapter_index": 1}).json()
    assert "BAU" in preview["translated_text"]
    download = client.get(f"/api/books/{book['id']}/download")
    assert download.status_code == 200
    assert download.content[:2] == b"PK"


def test_progress_without_a_job(client, sample_epub):
    _, book = _upload(client, sample_epub)
    progress = client.get(f"/api/books/{book['id']}/progress").json()
    assert progress == {
        "status": "uploaded",
        "running": False,
        "total_units": book["total_chapters"],
        "completed_units": 0,
        "failed_units": [],
        "in_flight": [],
        "started_at": None,
        "eta_seconds": None,
        "recent_events": [],
        "config": None,
        "queue_status": None,
        "queue": None,
    }
    assert client.get("/api/books/999/progress").status_code == 404


def test_progress_keeps_the_recent_log_newest_first(client, sample_epub):
    provider, book = _upload(client, sample_epub)
    events = _run(client, book["id"], provider["id"])
    assert all("ts" in e for e in events)

    progress = client.get(f"/api/books/{book['id']}/progress").json()
    assert progress["status"] == "completed" and progress["running"] is False
    assert progress["completed_units"] == book["total_chapters"]
    assert progress["started_at"] is not None
    logged = progress["recent_events"]
    assert logged[0]["event"] == "job_complete" and logged[-1]["event"] == "started"
    assert [e["ts"] for e in logged] == sorted((e["ts"] for e in logged), reverse=True)


def test_delete_book_removes_rows_and_files(client, sample_epub):
    import sqlite3
    from pathlib import Path

    from app.core.config import settings

    provider, book = _upload(client, sample_epub)
    _run(client, book["id"], provider["id"])
    client.post(f"/api/glossary/{book['id']}/entry", json={"source_term": "A", "target_term": "B"})
    with sqlite3.connect(settings.db_path) as conn:
        paths = conn.execute(
            "select original_path, translated_path from books where id = ?", (book["id"],)
        ).fetchone()
    assert all(Path(p).exists() for p in paths)
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute(
            "insert into bookmarks (book_id, unit, block, quote, reason, status) "
            "values (?, 0, 0, 'q', 'r', 'open')",
            (book["id"],),
        )
    assert len(client.get(f"/api/books/{book['id']}/bookmarks").json()) == 1

    assert client.delete(f"/api/books/{book['id']}").json() == {"status": "deleted"}
    assert client.get(f"/api/books/{book['id']}").status_code == 404
    assert client.get(f"/api/glossary/{book['id']}").json() == []
    assert not any(Path(p).exists() for p in paths)
    with sqlite3.connect(settings.db_path) as conn:
        for table in ("chapters", "translation_jobs", "queue_items", "bookmarks"):
            assert conn.execute(f"select count(*) from {table}").fetchone() == (0,)
    assert client.delete(f"/api/books/{book['id']}").status_code == 404


def test_compendium_api_replaces_entries_and_keeps_the_user_flag(client, sample_epub):
    _, book = _upload(client, sample_epub)
    entries = [
        {"name": "Mara", "gender": "female", "aliases": ["Ma"], "notes": "Keeper."},
        {"name": "Old Tom", "kind": "character", "user_edited": False},
    ]
    assert client.put(f"/api/compendium/{book['id']}", json={"entries": entries}).status_code == 200
    got = client.get(f"/api/compendium/{book['id']}").json()
    assert [(e["name"], e["gender"], e["aliases"], e["user_edited"]) for e in got] == [
        ("Mara", "female", ["Ma"], True),
        ("Old Tom", "unknown", [], False),
    ]


def test_single_entries_are_edited_while_a_live_store_holds_the_book(client, sample_epub):
    from app.jobs import jobs

    _, book = _upload(client, sample_epub)
    bid = book["id"]
    store = client.portal.call(jobs.knowledge.acquire, "compendium", f"book:{bid}", bid, set())
    added = client.post(f"/api/compendium/{bid}/entry", json={"name": "Ghislaine"}).json()
    assert store.compendium.entries[0].gender == "unknown"
    url = f"/api/compendium/{bid}/entry/{added['id']}"
    edited = client.put(url, json={"name": "Ghislaine", "gender": "female"}).json()
    assert edited["user_edited"] and store.compendium.entries[0].gender == "female"
    assert client.delete(f"/api/compendium/{bid + 1}/entry/{added['id']}").status_code == 404
    assert client.delete(url).status_code == 200 and store.compendium.entries == []
    jobs.knowledge.release(store)

    term = client.post(
        f"/api/glossary/{bid}/entry", json={"source_term": "Mara", "target_term": "Mara"}
    )
    url = f"/api/glossary/{bid}/entry/{term.json()['id']}"
    client.put(url, json={"source_term": "Mara", "target_term": "Marta"})
    assert [g["target_term"] for g in client.get(f"/api/glossary/{bid}").json()] == ["Marta"]
    assert client.delete(url).json() == {"status": "deleted"}
