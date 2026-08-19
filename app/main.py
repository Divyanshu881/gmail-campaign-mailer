"""Gmail Campaign Mailer - FastAPI application entrypoint.

Run with:
    venv/bin/uvicorn app.main:app --reload
"""

import logging

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app import pages
from app.routers import api, campaigns, gmail_auth, gmail_send

logger = logging.getLogger(__name__)

app = FastAPI(title="Gmail Campaign Mailer", version="0.3.0")

app.include_router(gmail_auth.router)
app.include_router(gmail_send.router)
app.include_router(campaigns.router)
app.include_router(api.router)


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