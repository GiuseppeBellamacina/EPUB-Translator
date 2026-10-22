"""Refresh the bundled price snapshot used when the live price list is unreachable.

    docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps \
        backend python scripts/snapshot_prices.py
"""

import json
import time

import httpx

from app.core.config import settings
from app.services.pricing import FALLBACK_FILE, _select

MODELS = [
    "gpt-4.1-nano",
    "gpt-4o-mini",
    "gpt-5-nano",
    "gpt-4.1-mini",
    "gpt-5-mini",
    "gpt-5.4-mini",
    "gpt-4.1",
    "gpt-5.6-luna",
    "claude-haiku-5-5",
    "claude-haiku-4-5",
    "claude-sonnet-5-5",
    "claude-opus-5-5",
]

prices = _select(httpx.get(settings.pricing_url, timeout=30).json())
FALLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
FALLBACK_FILE.write_text(
    json.dumps({"fetched_at": time.time(), "models": {m: prices[m] for m in MODELS}}, indent=1)
    + "\n",
    encoding="utf-8",
)
print(f"Wrote {len(MODELS)} models to {FALLBACK_FILE}")
