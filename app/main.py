from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.auth import admin_context_middleware, router as auth_router
from app.site_update import router as site_update_router

app = FastAPI()
app.include_router(auth_router)
app.include_router(site_update_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.middleware("http")(admin_context_middleware)

