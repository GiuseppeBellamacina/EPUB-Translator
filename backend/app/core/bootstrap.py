"""Provider bootstrap — create/update LLM providers from API keys and config.yaml on startup.

Keys come from the mounted .env file (``EPUB_ENV_FILE``) and the process environment.
Names are normalized, so ``OPENAI-API-KEY`` and ``OPENAI_API_KEY`` are equivalent.

``config.yaml`` ``providers:`` entries are upserted by name; an entry whose
``api_key_env`` is missing from the environment is skipped. Without a
``providers:`` section, a provider is created for every known key found.
"""

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import decrypt_api_key, encrypt_api_key
from app.db.models import ProviderConfig

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Providers auto-created from known keys when config.yaml declares none.
DEFAULT_PROVIDERS: dict[str, dict[str, Any]] = {
    "OPENAI_API_KEY": {"name": "openai", "type": "openai", "default_model": "gpt-4.1-nano"},
    "OPENROUTER_API_KEY": {
        "name": "openrouter",
        "type": "custom",
        "base_url": OPENROUTER_BASE_URL,
        "default_model": "nvidia/nemotron-3-super-120b-a12b:free",
    },
    "ANTHROPIC_API_KEY": {
        "name": "anthropic",
        "type": "anthropic",
        "default_model": "claude-haiku-4-5",
    },
}


def _normalize(name: str) -> str:
    return name.strip().upper().replace("-", "_")


def load_keys(env_file: Path | None = None) -> dict[str, str]:
    """Read API keys from the process env and the .env file (file wins), normalized."""
    keys = {_normalize(k): v for k, v in os.environ.items() if v}
    env_file = env_file or settings.env_file
    if env_file and env_file.is_file():
        keys.update({_normalize(k): v for k, v in dotenv_values(env_file).items() if v})
    return keys


def load_config(config_file: Path | None = None) -> dict[str, Any]:
    config_file = config_file or settings.config_file
    if not config_file.is_file():
        return {}
    return yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}


def resolve_providers(config: dict[str, Any], keys: dict[str, str]) -> list[dict[str, Any]]:
    """Return provider specs (with the resolved ``api_key``) that can be configured."""
    declared = config.get("providers")
    if declared is None:
        declared = [
            {**spec, "api_key_env": env} for env, spec in DEFAULT_PROVIDERS.items() if env in keys
        ]

    resolved = []
    for spec in declared:
        key_env = spec.get("api_key_env")
        api_key = keys.get(_normalize(key_env)) if key_env else None
        if key_env and not api_key:
            logger.info("Skipping provider %r: %s not set", spec.get("name"), key_env)
            continue
        resolved.append({**spec, "api_key": api_key})
    return resolved


async def bootstrap_providers(db: AsyncSession) -> list[str]:
    """Upsert providers by name. Returns the names configured."""
    specs = resolve_providers(load_config(), load_keys())
    for spec in specs:
        result = await db.execute(select(ProviderConfig).where(ProviderConfig.name == spec["name"]))
        provider = result.scalar_one_or_none()
        if provider is None:
            provider = ProviderConfig(name=spec["name"])
            db.add(provider)

        provider.provider_type = spec["type"]
        provider.base_url = spec.get("base_url")
        provider.default_model = spec.get("default_model")
        provider.params = spec.get("params")
        provider.is_active = True

        api_key = spec["api_key"]
        current = _safe_decrypt(provider.api_key_encrypted)
        if api_key != current:
            provider.api_key_encrypted = encrypt_api_key(api_key) if api_key else None

    await db.commit()
    names = [s["name"] for s in specs]
    if names:
        logger.info("Bootstrapped providers: %s", ", ".join(names))
    return names


def _safe_decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return decrypt_api_key(value)
    except Exception:
        # Encrypted with a different key: treat as changed so it gets re-encrypted.
        return None
