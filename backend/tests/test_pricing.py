import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.services import pricing
from app.services.cost_estimator import TokenProfile, estimate, usage
from app.services.pricing import ModelPrice, PriceTable, get_prices

LIVE_LIST = {
    "gpt-x": {
        "litellm_provider": "openai",
        "mode": "chat",
        "input_cost_per_token": 1e-6,
        "output_cost_per_token": 4e-6,
    },
    "claude-test-5": {
        "litellm_provider": "anthropic",
        "mode": "chat",
        "input_cost_per_token": 2e-6,
        "output_cost_per_token": 1e-5,
        "supports_reasoning": True,
    },
    "embed": {"litellm_provider": "openai", "mode": "embedding", "input_cost_per_token": 1e-8},
    "other": {"litellm_provider": "mistral", "mode": "chat", "input_cost_per_token": 1e-6},
}


@pytest.fixture
def price_source(monkeypatch, tmp_path):
    """Serve LIVE_LIST from a fake URL; count downloads; isolated cache file."""
    calls = {"n": 0, "fail": False}

    def handler(request):
        calls["n"] += 1
        if calls["fail"]:
            return httpx.Response(503)
        return httpx.Response(200, json=LIVE_LIST)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        pricing.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(pricing.settings, "pricing_url", "https://prices.test/list.json")
    monkeypatch.setattr(pricing.settings, "data_dir", tmp_path)
    return calls


async def test_live_prices_are_filtered_and_cached(price_source):
    table = await get_prices()
    assert table.source == "live"
    assert set(table.models) == {"gpt-x", "claude-test-5"}
    assert table.models["claude-test-5"].reasoning and not table.models["gpt-x"].reasoning

    again = await get_prices()
    assert again.source == "cache" and price_source["n"] == 1


async def test_expired_cache_is_refreshed_and_kept_when_download_fails(price_source):
    await get_prices()
    cache = pricing._cache_file()
    data = json.loads(cache.read_text())
    data["fetched_at"] = time.time() - 48 * 3600
    cache.write_text(json.dumps(data))

    price_source["fail"] = True
    stale = await get_prices()
    assert stale.source == "stale-cache" and "gpt-x" in stale.models

    price_source["fail"] = False
    assert (await get_prices()).source == "live" and price_source["n"] == 3


async def test_bundled_snapshot_when_offline(monkeypatch, tmp_path):
    monkeypatch.setattr(pricing.settings, "data_dir", tmp_path)
    table = await get_prices()  # pricing_url is "" in tests
    assert table.source == "bundled"
    assert {"gpt-4.1-nano", "claude-haiku-5-5"} <= set(table.models)


PROFILE = TokenProfile(
    units=10, chunks=100, source_tokens=50_000, context_tokens=8_000, analysis_tokens=3_000
)


def test_review_and_language_increase_usage():
    english = usage(PROFILE, "english", review=False)
    italian = usage(PROFILE, "italian", review=False)
    reviewed = usage(PROFILE, "italian", review=True)
    assert italian.output_tokens > english.output_tokens
    assert reviewed.input_tokens > 2 * italian.input_tokens
    assert reviewed.output_tokens > italian.output_tokens
    # output: at least the translated text
    assert italian.output_tokens >= 50_000 * 1.25


def test_estimate_applies_prices_tokenizer_and_reasoning():
    prices = PriceTable(
        models={
            "gpt-x": ModelPrice("openai", 1e-6, 4e-6, reasoning=False),
            "gpt-r": ModelPrice("openai", 1e-6, 4e-6, reasoning=True),
            "claude-x": ModelPrice("anthropic", 1e-6, 4e-6, reasoning=False),
        },
        fetched_at=0,
        source="cache",
    )
    result = estimate(
        PROFILE,
        prices,
        "italian",
        {"openai": ["gpt-x", "gpt-r", "missing"], "anthropic": ["claude-x"]},
    )
    rows = {r["model"]: r for r in result["models"]}
    assert set(rows) == {"gpt-x", "gpt-r", "claude-x"}

    plain = rows["gpt-x"]["with_review"]
    base = usage(PROFILE, "italian", review=True)
    assert plain["cost"] == pytest.approx(base.input_tokens * 1e-6 + base.output_tokens * 4e-6)
    assert rows["gpt-r"]["with_review"]["output_tokens"] == pytest.approx(
        2 * plain["output_tokens"], 1e-3
    )
    assert rows["claude-x"]["with_review"]["input_tokens"] > plain["input_tokens"]
    assert rows["gpt-x"]["without_review"]["cost"] < plain["cost"]
    assert [r["model"] for r in result["models"]][0] == "gpt-x"  # sorted by cost


def test_estimate_endpoint(db, sample_epub):
    from app.main import app

    with TestClient(app) as client:
        with open(sample_epub, "rb") as f:
            book = client.post("/api/upload", files={"file": ("s.epub", f)}).json()
        data = client.get(f"/api/books/{book['id']}/estimate").json()

    assert data["prices_source"] == "bundled"
    assert data["profile"]["chunks"] >= 3 and data["profile"]["source_tokens"] > 100
    providers = {r["provider"] for r in data["models"]}
    assert providers == {"openai", "anthropic"}
    assert all(r["with_review"]["cost"] > r["without_review"]["cost"] > 0 for r in data["models"])
