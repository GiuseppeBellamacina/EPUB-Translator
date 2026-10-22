import os
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.main import app
from tests.conftest import ScriptedLLM


@pytest.fixture
def client(db, monkeypatch):
    from app.services.job_runner import recent_events

    recent_events.clear()  # book ids restart with the fresh schema
    monkeypatch.setattr("app.services.job_runner.create_llm", lambda cfg: ScriptedLLM(delay=0.02))
    with TestClient(app) as c:
        yield c


def _setup(client, sample_epub, books=2):
    provider = client.post("/api/providers", json={"name": "fake", "provider_type": "fake"}).json()
    ids = []
    for _ in range(books):
        with open(sample_epub, "rb") as f:
            ids.append(client.post("/api/upload", files={"file": ("s.epub", f)}).json()["id"])
    return provider["id"], ids


def _wait(client, until, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        queue = client.get("/api/queue").json()
        if until(queue):
            return queue
        time.sleep(0.05)
    raise AssertionError(f"queue did not settle: {queue}")


def _terms(client, book_id):
    return {e["source_term"] for e in client.get(f"/api/glossary/{book_id}").json()}


def _status(client, book_id):
    return client.get(f"/api/books/{book_id}").json()["status"]


@pytest.mark.parametrize("keep", [False, True])
def test_queue_translates_books_in_order_and_carries_the_glossary_on_request(
    client, sample_epub, keep
):
    provider_id, (first, second) = _setup(client, sample_epub)
    client.post(f"/api/glossary/{first}/entry", json={"source_term": "Moon", "target_term": "Luna"})

    r = client.post(
        "/api/queue",
        json={"book_ids": [first, second], "provider_id": provider_id, "keep_glossary": keep},
    )
    assert r.json() == {"queued": 2}
    queue = _wait(client, lambda q: not q["running"])

    assert [i["book_id"] for i in queue["items"]] == [first, second]
    assert [i["status"] for i in queue["items"]] == ["done", "done"]
    assert _status(client, first) == _status(client, second) == "completed"
    assert ("Moon" in _terms(client, second)) is keep
    # the run's settings are kept with the book, so the UI can show and resume with them
    config = client.get(f"/api/books/{second}/progress").json()["config"]
    assert config["provider_id"] == provider_id and config["enable_review"] is True


def test_stop_pauses_the_current_book_and_halts_the_queue(client, sample_epub):
    provider_id, (first, second) = _setup(client, sample_epub)
    client.post("/api/queue", json={"book_ids": [first, second], "provider_id": provider_id})
    _wait(client, lambda q: q["items"][0]["status"] == "running")
    deadline = time.time() + 30  # stop once a checkpoint is saved, so there is something to resume
    while not any(
        e["event"] == "chunk_done"
        for e in client.get(f"/api/books/{first}/progress").json()["recent_events"]
    ):
        assert time.time() < deadline
        time.sleep(0.02)
    client.post("/api/queue/stop")

    queue = _wait(client, lambda q: not q["running"])
    assert [i["status"] for i in queue["items"]] == ["paused", "pending"]
    assert _status(client, first) == "paused" and _status(client, second) == "uploaded"
    assert client.get(f"/api/books/{first}/progress").json()["queue_status"] == "paused"

    client.post("/api/queue/start")  # resumes the paused book first
    queue = _wait(client, lambda q: not q["running"])
    assert [i["status"] for i in queue["items"]] == ["done", "done"]
    assert (
        "resuming"
        in client.get(f"/api/books/{first}/progress").json()["recent_events"][-1]["message"]
    )


def test_a_book_that_cannot_start_does_not_block_the_queue(client, sample_epub):
    provider_id, (broken, ok) = _setup(client, sample_epub)
    with sqlite3.connect(settings.db_path) as conn:
        (path,) = conn.execute("select original_path from books where id = ?", (broken,)).fetchone()
    os.remove(path)

    client.post("/api/queue", json={"book_ids": [broken, ok], "provider_id": provider_id})
    queue = _wait(client, lambda q: not q["running"])
    assert [i["status"] for i in queue["items"]] == ["failed", "done"]
    assert queue["items"][0]["error"]

    client.delete("/api/queue")  # clear finished
    assert client.get("/api/queue").json()["items"] == []


def test_closing_the_socket_does_not_pause_the_job(client, sample_epub):
    provider_id, (book,) = _setup(client, sample_epub, books=1)
    with client.websocket_connect(f"/ws/translate/{book}") as ws:
        ws.send_json({"action": "start", "provider_id": provider_id})
        assert ws.receive_json()["event"] == "started"
    _wait(client, lambda q: not q["running"])
    assert _status(client, book) == "completed"
    # nothing to follow any more: "watch" closes at once
    with client.websocket_connect(f"/ws/translate/{book}") as ws:
        ws.send_json({"action": "watch"})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
