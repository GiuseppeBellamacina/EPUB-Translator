"""Providers: CRUD, live model lists, connection test."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ProviderCreate,
    ProviderModelsRequest,
    ProviderResponse,
    ProviderUpdate,
    TestConnectionRequest,
)
from app.core.encryption import decrypt_api_key, encrypt_api_key
from app.core.llm_factory import LLMConfig, test_llm_connection
from app.db.database import get_db
from app.db.models import (
    ProviderConfig,
)
from app.services.model_catalog import list_models
from app.services.pricing import get_prices

router = APIRouter()


router = APIRouter()


# === PROVIDERS ===


@router.get("/providers", response_model=list[ProviderResponse])
async def list_providers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProviderConfig).where(ProviderConfig.is_active.is_(True)))
    return result.scalars().all()


@router.post("/providers", response_model=ProviderResponse)
async def create_provider(data: ProviderCreate, db: AsyncSession = Depends(get_db)):
    provider = ProviderConfig(
        name=data.name,
        provider_type=data.provider_type,
        api_key_encrypted=encrypt_api_key(data.api_key) if data.api_key else None,
        base_url=data.base_url,
        default_model=data.default_model,
        params=data.params,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


@router.put("/providers/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: int, data: ProviderUpdate, db: AsyncSession = Depends(get_db)
):
    """Edit a provider. Editing a config.yaml provider makes it user-owned (bootstrap skips it)."""
    provider = await db.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    changes = data.model_dump(exclude_unset=True)
    api_key = changes.pop("api_key", None)
    for field, value in changes.items():
        setattr(provider, field, value)
    if api_key is not None:  # None keeps the stored key, "" clears it
        provider.api_key_encrypted = encrypt_api_key(api_key) if api_key else None
    provider.source = "user"
    await db.commit()
    await db.refresh(provider)
    return provider


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(404, "Provider not found")
    await db.delete(provider)
    await db.commit()
    return {"status": "deleted"}


@router.get("/providers/{provider_id}/models")
async def provider_models(
    provider_id: int, refresh: bool = False, db: AsyncSession = Depends(get_db)
):
    """Chat models the provider serves, listed live from its API (cached a few minutes)."""
    provider = await db.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    api_key = decrypt_api_key(provider.api_key_encrypted) if provider.api_key_encrypted else None
    try:
        return await list_models(
            provider.provider_type, api_key, provider.base_url, await get_prices(), refresh
        )
    except Exception as e:
        raise HTTPException(502, f"Could not list models from {provider.name}: {e}")


@router.post("/providers/models")
async def unsaved_provider_models(data: ProviderModelsRequest):
    """Models of a provider that is not saved yet; a failure also means a bad key or URL."""
    try:
        return await list_models(
            data.provider_type, data.api_key or None, data.base_url or None, await get_prices()
        )
    except Exception as e:
        raise HTTPException(502, f"Could not list models: {e}")


@router.post("/providers/test")
async def test_provider(data: TestConnectionRequest):
    config = LLMConfig(
        provider=data.provider_type,
        model=data.model,
        api_key=data.api_key,
        base_url=data.base_url,
        temperature=data.temperature,
    )
    result = await test_llm_connection(config)
    return result
