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


def _slow(monkeypatch):
    """Slow calls, so a stop lands while the (tiny) sample book is still translating."""
    monkeypatch.setattr("app.services.job_runner.create_llm", lambda cfg: ScriptedLLM(delay=0.15))


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
    mara = {"name": "Mara", "gender": "female"}
    client.put(f"/api/compendium/{first}", json={"entries": [mara]})

    r = client.post(
        "/api/queue",
        json={
            "book_ids": [first, second],
            "provider_id": provider_id,
            "keep_glossary": keep,
            "keep_compendium": keep,
        },
    )
    assert r.json() == {"queued": 2}
    queue = _wait(client, lambda q: not q["running"])

    assert [i["book_id"] for i in queue["items"]] == [first, second]
    assert [i["status"] for i in queue["items"]] == ["done", "done"]
    assert _status(client, first) == _status(client, second) == "completed"
    assert ("Moon" in _terms(client, second)) is keep
    carried = [(e["name"], e["gender"]) for e in client.get(f"/api/compendium/{second}").json()]
    assert (("Mara", "female") in carried) is keep
    # the run's settings are kept with the book, so the UI can show and resume with them
    config = client.get(f"/api/books/{second}/progress").json()["config"]
    assert config["provider_id"] == provider_id and config["enable_review"] is True


def test_stop_pauses_the_current_book_and_halts_the_queue(client, sample_epub, monkeypatch):
    _slow(monkeypatch)
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
    assert [i["status"] for i in queue["items"]] == ["paused", "paused"]
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


def test_starting_another_book_does_not_resume_paused_ones(client, sample_epub, monkeypatch):
    _slow(monkeypatch)
    provider_id, (first, second, other) = _setup(client, sample_epub, books=3)
    client.post("/api/queue", json={"book_ids": [first, second], "provider_id": provider_id})
    _wait(client, lambda q: q["items"][0]["status"] == "running")
    client.post("/api/queue/stop")
    _wait(client, lambda q: not q["running"])

    with client.websocket_connect(f"/ws/translate/{other}") as ws:
        ws.send_json({"action": "start", "provider_id": provider_id})
        while ws.receive_json()["event"] != "job_complete":
            pass
    queue = _wait(client, lambda q: not q["running"])
    status = {i["book_id"]: i["status"] for i in queue["items"]}
    assert status == {other: "done", first: "paused", second: "paused"}
    assert _status(client, second) == "uploaded"

    client.post("/api/queue/start")
    queue = _wait(client, lambda q: not q["running"])
    assert {i["status"] for i in queue["items"]} == {"done"}


def test_keep_glossary_never_carries_from_an_earlier_batch(client, sample_epub):
    provider_id, (old, first, second) = _setup(client, sample_epub, books=3)
    client.post(f"/api/glossary/{old}/entry", json={"source_term": "Moon", "target_term": "Luna"})
    client.post("/api/queue", json={"book_ids": [old], "provider_id": provider_id})
    _wait(client, lambda q: not q["running"] and q["items"][0]["status"] == "done")

    client.post(f"/api/glossary/{first}/entry", json={"source_term": "Sun", "target_term": "Sole"})
    client.post(
        "/api/queue",
        json={"book_ids": [first, second], "provider_id": provider_id, "keep_glossary": True},
    )
    _wait(client, lambda q: not q["running"] and all(i["status"] == "done" for i in q["items"]))
    assert "Moon" not in _terms(client, first)
    assert {"Sun"} <= _terms(client, second) and "Moon" not in _terms(client, second)


def test_books_added_to_a_running_queue_carry_its_glossary_and_compendium(
    client, sample_epub, monkeypatch
):
    _slow(monkeypatch)
    provider_id, (first, second, other) = _setup(client, sample_epub, books=3)
    client.post(f"/api/glossary/{first}/entry", json={"source_term": "Moon", "target_term": "Luna"})
    client.put(f"/api/compendium/{first}", json={"entries": [{"name": "Mara", "gender": "female"}]})
    client.post(
        "/api/queue",
        json={
            "book_ids": [first],
            "provider_id": provider_id,
            "keep_glossary": True,
            "keep_compendium": True,
        },
    )
    batch = _wait(client, lambda q: q["items"][0]["status"] == "running")["items"][0]["batch_id"]
    # another queue started meanwhile: it runs after, and never carries from this one
    client.post("/api/queue", json={"book_ids": [other], "provider_id": provider_id})
    assert client.post(f"/api/queue/{batch}/books", json={"book_ids": [second]}).json() == {
        "queued": 1
    }

    queue = _wait(client, lambda q: not q["running"])
    assert [i["book_id"] for i in queue["items"]] == [first, second, other]
    assert [i["batch_id"] == batch for i in queue["items"]] == [True, True, False]
    assert {i["status"] for i in queue["items"]} == {"done"}
    assert "Moon" in _terms(client, second) and "Moon" not in _terms(client, other)
    names = [e["name"] for e in client.get(f"/api/compendium/{second}").json()]
    assert "Mara" in names
    assert client.post("/api/queue/999/books", json={"book_ids": [other]}).status_code == 400


def test_books_added_to_a_paused_queue_wait_for_its_resume(client, sample_epub, monkeypatch):
    _slow(monkeypatch)
    provider_id, (first, second, third) = _setup(client, sample_epub, books=3)
    client.post("/api/queue", json={"book_ids": [first, second], "provider_id": provider_id})
    batch = _wait(client, lambda q: q["items"][0]["status"] == "running")["items"][0]["batch_id"]
    client.post("/api/queue/stop")
    _wait(client, lambda q: not q["running"])

    client.post(f"/api/queue/{batch}/books", json={"book_ids": [third]})
    queue = _wait(client, lambda q: not q["running"])
    assert [i["status"] for i in queue["items"]] == ["paused", "paused", "paused"]

    client.post("/api/queue/start")
    queue = _wait(client, lambda q: not q["running"] and q["items"][-1]["status"] == "done")
    assert [i["book_id"] for i in queue["items"]] == [first, second, third]
    assert {i["status"] for i in queue["items"]} == {"done"}


def test_progress_shows_the_queue_of_the_book(client, sample_epub):
    provider_id, (first, second) = _setup(client, sample_epub)
    client.post("/api/queue", json={"book_ids": [first, second], "provider_id": provider_id})
    _wait(client, lambda q: not q["running"])

    queue = client.get(f"/api/books/{second}/progress").json()["queue"]
    assert [(i["book_id"], i["status"]) for i in queue["items"]] == [
        (first, "done"),
        (second, "done"),
    ]
    # a one-book start from the translate page is not shown as a queue
    provider = {"provider_id": provider_id}
    with client.websocket_connect(f"/ws/translate/{first}") as ws:
        ws.send_json({"action": "start", **provider})
        while ws.receive_json()["event"] != "job_complete":
            pass
    assert client.get(f"/api/books/{first}/progress").json()["queue"] is None


def test_waiting_books_can_be_reordered_while_the_queue_runs(client, sample_epub, monkeypatch):
    _slow(monkeypatch)
    provider_id, (a, b, c, d) = _setup(client, sample_epub, books=4)
    client.post("/api/queue", json={"book_ids": [a, b, c, d], "provider_id": provider_id})
    queue = _wait(client, lambda q: q["items"][0]["status"] == "running")
    batch = queue["items"][0]["batch_id"]
    ids = {i["book_id"]: i["id"] for i in queue["items"]}

    bad = client.put(f"/api/queue/{batch}/order", json={"item_ids": [ids[a], ids[b]]})
    assert bad.status_code == 400  # the running book cannot move, all waiting ones must be listed
    order = [ids[d], ids[b], ids[c]]
    assert client.put(f"/api/queue/{batch}/order", json={"item_ids": order}).status_code == 200

    queue = _wait(client, lambda q: not q["running"])
    assert [i["book_id"] for i in queue["items"]] == [a, d, b, c]
    assert {i["status"] for i in queue["items"]} == {"done"}


def _peak_running(client, until, timeout=60):
    """Most books running at the same time until ``until(queue)``."""
    peak, deadline = 0, time.time() + timeout
    while time.time() < deadline:
        queue = client.get("/api/queue").json()
        peak = max(peak, sum(i["status"] == "running" for i in queue["items"]))
        if until(queue):
            return peak, queue
        time.sleep(0.02)
    raise AssertionError("queue did not settle")


def test_books_run_in_parallel_but_a_carrying_queue_stays_in_order(
    client, sample_epub, monkeypatch
):
    _slow(monkeypatch)
    provider_id, (a, b, c, d) = _setup(client, sample_epub, books=4)
    assert client.put("/api/settings", json={"max_parallel_books": 0}).status_code == 422
    assert (
        client.put("/api/settings", json={"max_parallel_books": 2}).json()["max_parallel_books"]
        == 2
    )
    try:
        # a queue that carries the glossary: in order; a second queue alongside it
        keep = {"provider_id": provider_id, "keep_glossary": True}
        client.post("/api/queue", json={"book_ids": [a, b], **keep})
        client.post("/api/queue", json={"book_ids": [c], "provider_id": provider_id})
        running = _wait(client, lambda q: sum(i["status"] == "running" for i in q["items"]) == 2)
        assert {i["book_id"] for i in running["items"] if i["status"] == "running"} == {a, c}

        peak, queue = _peak_running(client, lambda q: not q["running"])
        assert peak <= 2 and {i["status"] for i in queue["items"]} == {"done"}

        # a queue that carries nothing runs its books side by side
        client.post("/api/queue", json={"book_ids": [d, a], "provider_id": provider_id})
        peak, _ = _peak_running(client, lambda q: not q["running"])
        assert peak == 2
    finally:
        client.put("/api/settings", json={"max_parallel_books": 1})


def test_books_on_one_provider_share_its_rate_limiter():
    from app.services.job_runner import _limiter_for

    assert _limiter_for(1, 0.5) is _limiter_for(1, 0.5)
    assert _limiter_for(1, 0.5) is not _limiter_for(2, 0.5)
    assert _limiter_for(1, 0) is None
