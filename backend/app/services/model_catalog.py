"""
Model catalog — the models a configured provider actually serves, for the UI picker.

Listed live through each provider's API (official SDKs for OpenAI and Anthropic,
the OpenAI SDK for OpenAI-compatible endpoints such as OpenRouter, Ollama's
``/api/tags``), filtered to chat models, priced when the price is known, and
cached for a few minutes per provider configuration.
"""

import re
import time
from dataclasses import asdict, dataclass

import httpx
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.core.config import settings
from app.services.pricing import ModelPrice, PriceTable

CACHE_TTL = 600
_cache: dict[tuple, tuple[float, list["ModelOption"]]] = {}

# OpenAI's /models also returns embeddings, audio, image, moderation... models
_OPENAI_CHAT = re.compile(r"(gpt-|chatgpt-|o\d)")
_OPENAI_NON_CHAT = (
    "embedding", "tts", "whisper", "dall-e", "image", "audio", "realtime", "transcribe",
    "moderation", "search", "computer-use", "deep-research", "codex", "instruct", "-pro",
)  # fmt: skip
_DATED = re.compile(r"-(\d{4}-\d{2}-\d{2}|\d{8}|\d{4})$")  # -2025-04-14, -20250414, -0125


@dataclass
class ModelOption:
    id: str
    label: str
    input_per_million: float | None = None
    output_per_million: float | None = None
    reasoning: bool | None = None


def _without_dated_snapshots(ids: list[str]) -> list[str]:
    """Drop ``gpt-4.1-2025-04-14`` when the ``gpt-4.1`` alias is listed too."""
    names = set(ids)
    return [i for i in ids if not (_DATED.search(i) and _DATED.sub("", i) in names)]


def price_for(provider_type: str, model: str, prices: PriceTable) -> ModelPrice | None:
    """Known price of a model; OpenAI-compatible routers name models ``vendor/model``."""
    if provider_type in ("openai", "anthropic"):
        return prices.models.get(model)
    if model.endswith(":free"):
        return ModelPrice("openai", 0.0, 0.0, reasoning=False)
    vendor, _, name = model.partition("/")
    price = prices.models.get(name) if vendor in ("openai", "anthropic") else None
    return price


def _priced(option: ModelOption, price: ModelPrice | None) -> ModelOption:
    if price is not None:
        option.input_per_million = price.input_per_token * 1e6
        option.output_per_million = price.output_per_token * 1e6
        option.reasoning = price.reasoning
    return option


async def _fetch(
    provider_type: str, api_key: str | None, base_url: str | None
) -> list[ModelOption]:
    match provider_type:
        case "fake":
            return [ModelOption("fake-meow", "fake-meow (offline test provider)")]
        case "openai":
            client = AsyncOpenAI(api_key=api_key, base_url=base_url or None)
            ids = [m.id async for m in client.models.list()]
            ids = [
                i
                for i in ids
                if _OPENAI_CHAT.match(i) and not any(x in i for x in _OPENAI_NON_CHAT)
            ]
            return [ModelOption(i, i) for i in _without_dated_snapshots(ids)]
        case "anthropic":
            client = AsyncAnthropic(api_key=api_key, base_url=base_url or None)
            return [ModelOption(m.id, m.display_name) async for m in client.models.list(limit=1000)]
        case "custom":
            client = AsyncOpenAI(api_key=api_key or "not-needed", base_url=base_url)
            options = []
            async for m in client.models.list():
                extra = m.model_extra or {}
                option = ModelOption(m.id, extra.get("name") or m.id)
                pricing = extra.get("pricing") or {}  # OpenRouter: USD per token, as strings
                try:
                    prompt, completion = float(pricing["prompt"]), float(pricing["completion"])
                    if prompt >= 0 and completion >= 0:  # routers report -1 (variable price)
                        option.input_per_million = prompt * 1e6
                        option.output_per_million = completion * 1e6
                except (KeyError, TypeError, ValueError):
                    pass
                options.append(option)
            return options
        case "ollama":
            url = base_url or settings.ollama_base_url
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(f"{url}/api/tags")
                    response.raise_for_status()
            except httpx.ConnectError:
                raise ConnectionError(f"Ollama is not running at {url}") from None
            return [ModelOption(m["name"], m["name"], 0.0, 0.0) for m in response.json()["models"]]
        case _:
            raise ValueError(f"Unsupported provider: {provider_type}")


async def list_models(
    provider_type: str,
    api_key: str | None,
    base_url: str | None,
    prices: PriceTable,
    refresh: bool = False,
) -> list[dict]:
    """Chat models of a provider: priced ones cheapest first, then the rest by name."""
    key = (provider_type, base_url, api_key)
    cached = _cache.get(key)
    if cached and not refresh and time.time() - cached[0] < CACHE_TTL:
        options = cached[1]
    else:
        options = await _fetch(provider_type, api_key, base_url)
        _cache[key] = (time.time(), options)

    priced = [
        (
            _priced(ModelOption(**asdict(o)), price_for(provider_type, o.id, prices))
            if o.input_per_million is None
            else o
        )
        for o in options
    ]
    priced.sort(
        key=lambda o: (
            o.input_per_million is None,
            (o.input_per_million or 0) + 4 * (o.output_per_million or 0),
            o.label.lower(),
        )
    )
    return [asdict(o) for o in priced]
