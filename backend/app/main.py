from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import routers
from app.api.websocket import ws_router
from app.core.bootstrap import bootstrap_providers, load_config
from app.core.config import settings
from app.db.database import async_session, init_db
from app.jobs import jobs
from app.services import app_settings
from app.services.job_store import recover_interrupted_jobs

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in routers:
    app.include_router(router, prefix="/api")
app.include_router(ws_router)


@app.on_event("startup")
async def startup():
    settings.ensure_dirs()
    settings.apply_overrides(load_config().get("translation") or {})
    app_settings.migrate_legacy()
    await init_db()
    await recover_interrupted_jobs()
    jobs.reset()  # a fresh queue state for this app run
    await jobs.recover()
    async with async_session() as db:
        await bootstrap_providers(db)


@app.on_event("shutdown")
async def shutdown():
    await jobs.scheduler.shutdown()  # running books are paused with their progress saved


@app.get("/health")
async def health():
    return {"status": "ok"}
