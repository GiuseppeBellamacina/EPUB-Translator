"""
Pricing — per-token prices of OpenAI and Anthropic chat models, kept up to date.

Neither provider publishes a pricing API, so prices come from LiteLLM's public,
community-maintained price list (``settings.pricing_url``). The relevant entries
are cached in ``data/pricing_cache.json`` and refreshed every
``settings.pricing_refresh_hours``. If the list cannot be fetched, a stale cache
is used, then the snapshot bundled with the code (``app/data/pricing_fallback.json``).
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.core.config import settings
from app.core.llm_factory import thinks_by_default

logger = logging.getLogger(__name__)

PROVIDERS = {"openai", "anthropic"}
FALLBACK_FILE = Path(__file__).resolve().parent.parent / "data" / "pricing_fallback.json"
_lock = asyncio.Lock()


@dataclass(frozen=True)
class ModelPrice:
    provider: str
    input_per_token: float
    output_per_token: float
    reasoning: bool  # thinks by default: thinking tokens are billed as output


@dataclass(frozen=True)
class PriceTable:
    models: dict[str, ModelPrice]
    fetched_at: float  # unix time of the data's download
    source: str  # "live", "cache", "stale-cache" or "bundled"


def _cache_file() -> Path:
    return settings.data_dir / "pricing_cache.json"


def _select(raw: dict) -> dict[str, dict]:
    """Keep the OpenAI/Anthropic chat models with token prices."""
    return {
        name: {
            "provider": entry["litellm_provider"],
            "input_per_token": entry["input_cost_per_token"],
            "output_per_token": entry["output_cost_per_token"],
            "reasoning": thinks_by_default(
                entry["litellm_provider"], name, bool(entry.get("supports_reasoning"))
            ),
        }
        for name, entry in raw.items()
        if isinstance(entry, dict)
        and entry.get("litellm_provider") in PROVIDERS
        and entry.get("mode") == "chat"
        and entry.get("input_cost_per_token") is not None
        and entry.get("output_cost_per_token") is not None
    }


def _table(data: dict, source: str) -> PriceTable:
    return PriceTable(
        models={name: ModelPrice(**m) for name, m in data["models"].items()},
        fetched_at=data["fetched_at"],
        source=source,
    )


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


async def get_prices(force_refresh: bool = False) -> PriceTable:
    async with _lock:  # one download at a time
        cached = _read(_cache_file())
        max_age = settings.pricing_refresh_hours * 3600
        if cached and not force_refresh and time.time() - cached["fetched_at"] < max_age:
            return _table(cached, "cache")

        if settings.pricing_url:
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.get(settings.pricing_url)
                    response.raise_for_status()
                data = {"fetched_at": time.time(), "models": _select(response.json())}
                if data["models"]:
                    _cache_file().parent.mkdir(parents=True, exist_ok=True)
                    _cache_file().write_text(json.dumps(data), encoding="utf-8")
                    return _table(data, "live")
            except (httpx.HTTPError, ValueError) as e:
                logger.warning("Price list download failed: %s", e)

        if cached:
            return _table(cached, "stale-cache")
        return _table(json.loads(FALLBACK_FILE.read_text(encoding="utf-8")), "bundled")
