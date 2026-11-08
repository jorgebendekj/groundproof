from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from . import ALGORITHM_VERSION
from .bootstrap import init_db, seed
from .config import get_settings
from .db import SessionLocal
from .routers import field, plots, review


@asynccontextmanager
async def lifespan(_: FastAPI):
    if get_settings().insecure_defaults and not get_settings().demo_seed:
        raise RuntimeError("Refusing to start: set JWT_SECRET and ADMIN_PASSWORD when DEMO_SEED=false")
    init_db()
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title="GroundProof API", version=ALGORITHM_VERSION, lifespan=lifespan,
              description="Evidence to support EUDR due diligence. Not a certification.")
app.include_router(plots.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(field.router, prefix="/api")


@app.get("/health")
def health():
    s = get_settings()
    with SessionLocal() as db:
        db.execute(text("select 1"))
    return {"status": "ok", "version": ALGORITHM_VERSION, "cutoff_adapter": s.cutoff_adapter,
            "imagery_mode": s.imagery_mode, "tasking_enabled": s.iceye_enabled}


ROOT = Path(__file__).resolve().parents[2]
for mount, rel in (("/console", "console/standalone"), ("/field", "field-app")):
    d = ROOT / rel
    if d.is_dir():
        app.mount(mount, StaticFiles(directory=d, html=True), name=mount.strip("/"))


@app.get("/")
def index():
    return FileResponse(ROOT / "console/standalone/index.html") if (ROOT / "console/standalone/index.html").exists() \
        else {"name": "GroundProof API", "docs": "/docs"}
