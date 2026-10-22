import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(db):
    with TestClient(app) as c:
        yield c


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
