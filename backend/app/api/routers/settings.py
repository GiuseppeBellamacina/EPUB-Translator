"""App settings and the translation defaults."""

from fastapi import APIRouter

from app.core.config import settings
from app.jobs import jobs
from app.services import app_settings

router = APIRouter()


router = APIRouter()


@router.get("/settings")
async def get_settings():
    """App settings, plus the translation defaults a provider's params override."""
    return {
        **app_settings.load().model_dump(),
        "defaults": {
            "requests_per_second": settings.requests_per_second,
            "max_concurrency": settings.max_concurrency,
            "max_retries": settings.llm_max_retries,
        },
    }


@router.put("/settings")
async def update_settings(data: app_settings.AppSettings):
    app_settings.save(data)
    if jobs.scheduler.running:
        jobs.scheduler.fill()  # more books in parallel start now; fewer as books finish
    return await get_settings()
