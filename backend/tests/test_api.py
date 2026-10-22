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

    monkeypatch.setattr("app.api.websocket.create_llm", lambda cfg: ScriptedLLM(delay=0.05))
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
