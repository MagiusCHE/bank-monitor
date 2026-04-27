from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .routes import accounts, bootstrap, groups, upload

app = FastAPI(title="Bank Monitor", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "bank-monitor"}


app.include_router(upload.router, prefix="/api")
app.include_router(accounts.router, prefix="/api")
app.include_router(bootstrap.router, prefix="/api")
app.include_router(groups.router, prefix="/api")
