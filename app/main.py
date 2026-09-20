"""Gmail Campaign Mailer - FastAPI application entrypoint.

Run with:
    venv/bin/uvicorn app.main:app --reload
"""

import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app import pages
from app.config import settings
from app.routers import admin, api, campaigns, gmail_auth, gmail_send

logger = logging.getLogger(__name__)

app = FastAPI(title="Gmail Campaign Mailer", version="0.4.0")

# The React UI is a separate origin (localhost:5173 in dev, a Vercel URL in
# prod). Bearer-token auth only, so no cookies/credentials are used.
_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(gmail_auth.router)
app.include_router(gmail_send.router)
app.include_router(campaigns.router)
app.include_router(api.router)
app.include_router(admin.router)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """Minimal dev test page."""
    return pages.render_index()


@app.get("/auth/supabase/callback", response_class=HTMLResponse)
def supabase_callback() -> str:
    """Completes the Supabase OAuth redirect (dev test page)."""
    return pages.render_supabase_callback()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)