import httpx
import pytest
from anthropic import AsyncAnthropic
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from app.services import model_catalog
from app.services.model_catalog import list_models, price_for
from app.services.pricing import ModelPrice, PriceTable

PRICES = PriceTable(
    models={
        "gpt-4.1-mini": ModelPrice("openai", 4e-7, 1.6e-6, False),
        "gpt-4.1-nano": ModelPrice("openai", 1e-7, 4e-7, False),
        "claude-haiku-5-5": ModelPrice("anthropic", 1e-7, 5e-7, True),
    },
    fetched_at=0,
    source="cache",
)

OPENAI_MODELS = [
    "gpt-4.1-mini", "gpt-4.1-mini-2025-04-14", "gpt-4.1-nano", "gpt-3.5-turbo",
    "gpt-3.5-turbo-0125", "text-embedding-3-small", "gpt-4o-mini-tts", "whisper-1",
    "gpt-image-1", "gpt-realtime", "gpt-5.5-pro", "o4-mini", "dall-e-3", "gpt-new",
]  # fmt: skip


def serve(payload):
    def handler(request):
        return httpx.Response(200, json=payload(request))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def fresh_cache():
    model_catalog._cache.clear()


async def test_openai_lists_chat_models_priced_first(monkeypatch):
    body = {"object": "list", "data": [{"id": i, "object": "model", "created": 0, "owned_by": "x"} for i in OPENAI_MODELS]}  # fmt: skip
    monkeypatch.setattr(
        model_catalog,
        "AsyncOpenAI",
        lambda **kw: AsyncOpenAI(**kw, http_client=serve(lambda r: body)),
    )
    models = await list_models("openai", "sk-test", None, PRICES)
    assert [m["id"] for m in models] == [
        "gpt-4.1-nano",  # priced, cheapest first
        "gpt-4.1-mini",
        "gpt-3.5-turbo",  # unpriced, by name; dated snapshots hidden behind aliases
        "gpt-new",
        "o4-mini",
    ]
    assert models[0]["input_per_million"] == pytest.approx(0.1)


async def test_anthropic_models_with_display_names(monkeypatch):
    body = {
        "data": [
            {"id": "claude-haiku-5-5", "display_name": "Claude Haiku 5.5", "type": "model",
             "created_at": "2026-01-01T00:00:00Z"},
            {"id": "claude-opus-9", "display_name": "Claude Opus 9", "type": "model",
             "created_at": "2026-01-01T00:00:00Z"},
        ],
        "has_more": False,
        "first_id": "claude-haiku-5-5",
        "last_id": "claude-opus-9",
    }  # fmt: skip
    monkeypatch.setattr(
        model_catalog,
        "AsyncAnthropic",
        lambda **kw: AsyncAnthropic(**kw, http_client=serve(lambda r: body)),
    )
    models = await list_models("anthropic", "sk-ant-test", None, PRICES)
    assert [(m["id"], m["label"], m["reasoning"]) for m in models] == [
        ("claude-haiku-5-5", "Claude Haiku 5.5", True),
        ("claude-opus-9", "Claude Opus 9", None),
    ]


async def test_openrouter_prices_from_the_listing(monkeypatch):
    body = {
        "data": [
            {"id": "openrouter/auto", "name": "Auto", "pricing": {"prompt": "-1", "completion": "-1"}},
            {"id": "google/gemma:free", "name": "Gemma (free)", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "x/model", "name": "X", "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
        ]
    }  # fmt: skip
    seen = []

    def payload(request):
        seen.append(str(request.url))
        return body

    monkeypatch.setattr(
        model_catalog,
        "AsyncOpenAI",
        lambda **kw: AsyncOpenAI(**kw, http_client=serve(payload)),
    )
    models = await list_models("custom", "or-key", "https://router.test/api/v1", PRICES)
    assert [(m["id"], m["input_per_million"]) for m in models] == [
        ("google/gemma:free", 0.0),
        ("x/model", pytest.approx(1.0)),
        ("openrouter/auto", None),  # variable price
    ]
    await list_models("custom", "or-key", "https://router.test/api/v1", PRICES)
    assert seen == ["https://router.test/api/v1/models"]  # second call served from cache


def test_price_for_router_names():
    assert price_for("custom", "openai/gpt-4.1-mini", PRICES) is PRICES.models["gpt-4.1-mini"]
    assert price_for("custom", "x/y:free", PRICES).input_per_token == 0
    assert price_for("custom", "x/unknown", PRICES) is None
    assert price_for("openai", "gpt-4.1-nano", PRICES) is PRICES.models["gpt-4.1-nano"]


def test_models_endpoint_and_single_model_estimate(db, sample_epub):
    from app.main import app

    with TestClient(app) as client:
        provider = client.post("/api/providers", json={"name": "f", "provider_type": "fake"}).json()
        assert client.get(f"/api/providers/{provider['id']}/models").json()[0]["id"] == "fake-meow"

        openai = client.post(
            "/api/providers", json={"name": "o", "provider_type": "openai", "api_key": "sk"}
        ).json()
        with open(sample_epub, "rb") as f:
            book = client.post("/api/upload", files={"file": ("s.epub", f)}).json()
        url = f"/api/books/{book['id']}/estimate"
        one = client.get(url, params={"provider_id": openai["id"], "model": "gpt-4.1-mini"}).json()
        assert [m["model"] for m in one["models"]] == ["gpt-4.1-mini"]
        unknown = client.get(url, params={"provider_id": openai["id"], "model": "nope"}).json()
        assert unknown["models"] == []
