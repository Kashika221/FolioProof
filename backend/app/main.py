"""FastAPI entry point."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings
from app.db.files import get_file_store
from app.db.mongo import get_repository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(
    title = "FolioProof",
    version = "1.0.0",
    description = (
        "Multi-source professional identity fusion with provenance. Every "
        "generated sentence is traceable to the source span behind it, and "
        "conflicting facts resolve by source precedence "
        "(resume > linkedin > github > cover letter)."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    "https://folio-proof.vercel.app"
    ],
    allow_credentials = True,
    allow_methods = ["*"],
    allow_headers = ["*"],
)

app.include_router(router)

@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "groq_configured": settings.groq_enabled,
        "github_token_configured": bool(settings.github_token),
        "llm_calls_per_build": "1 (2-3 on truncation retries)",
        "storage": get_repository().backend,
        "file_storage": get_file_store().backend,
        "source_priority": ["resume", "linkedin", "github", "cover_letter"],
    }