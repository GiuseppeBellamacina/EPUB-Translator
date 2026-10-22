from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.websocket import ws_router
from app.core.bootstrap import bootstrap_providers, load_config
from app.core.config import settings
from app.db.database import async_session, init_db
from app.services import job_runner
from app.services.job_store import recover_interrupted_jobs

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(ws_router)


@app.on_event("startup")
async def startup():
    settings.ensure_dirs()
    settings.apply_overrides(load_config().get("translation") or {})
    await init_db()
    await recover_interrupted_jobs()
    await job_runner.recover_queue()
    async with async_session() as db:
        await bootstrap_providers(db)


@app.on_event("shutdown")
async def shutdown():
    await job_runner.shutdown()  # the running book is paused with its progress saved


@app.get("/health")
async def health():
    return {"status": "ok"}
