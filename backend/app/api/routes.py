"""HTTP surface.

Profiles are persisted in MongoDB via `ProfileRepository`. A build record is a
single document -- the ProfileGraph dumped straight to JSON -- which is why a
document store suits this shape better than tables would.
"""
from __future__ import annotations

import base64
import logging
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel

from app.config import settings
from app.db.mongo import get_repository
from app.generate.portfolio import render_bundle, render_portfolio
from app.generate.themes import SECTIONS, THEMES, ThemeConfig
from app.models.claims import ProfileGraph
from app.pipeline import BuildInputs, build_profile

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

ALLOWED_SUFFIXES = {".pdf"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# storage helpers
# ---------------------------------------------------------------------------


def _save(build_id: str, payload: dict[str, Any]) -> None:
    get_repository().save(build_id, payload)


def _load(build_id: str) -> dict[str, Any]:
    record = get_repository().get(build_id)
    if record is None:
        raise HTTPException(404, f"unknown build id {build_id}")
    return record


def _graph_of(record: dict[str, Any]) -> ProfileGraph:
    return ProfileGraph.model_validate(record["graph"])


def _store_upload(file: UploadFile, build_id: str, label: str) -> Path:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"{label}: only PDF uploads are supported (got {suffix or 'none'})")

    dest_dir = settings.upload_path / build_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{label}{suffix}"

    size = 0
    with dest.open("wb") as out:
        while chunk := file.file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                dest.unlink(missing_ok=True)
                raise HTTPException(400, f"{label}: file exceeds 10 MB")
            out.write(chunk)
    return dest


# ---------------------------------------------------------------------------
# themes
# ---------------------------------------------------------------------------


@router.get("/themes")
def list_themes() -> dict[str, Any]:
    """Themes plus their default per-section palettes (drives the colour pickers)."""
    return {
        "sections": SECTIONS,
        "themes": [
            {
                "key": t.key,
                "label": t.label,
                "description": t.description,
                "palettes": {s: p.model_dump() for s, p in t.palettes.items()},
            }
            for t in THEMES.values()
        ],
    }


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


@router.post("/build")
async def build(
    resume: UploadFile = File(...),
    linkedin: UploadFile | None = File(None),
    cover_letter: UploadFile | None = File(None),
    github_username: str = Form(""),
    max_repos: int = Form(10),
) -> JSONResponse:
    """Ingest every supplied source and produce a fused profile."""
    build_id = uuid.uuid4().hex[:12]

    resume_path = _store_upload(resume, build_id, "resume")
    linkedin_path = _store_upload(linkedin, build_id, "linkedin") if linkedin else None
    cover_path = _store_upload(cover_letter, build_id, "cover_letter") if cover_letter else None

    result = build_profile(BuildInputs(
        resume_path=resume_path,
        linkedin_path=linkedin_path,
        cover_letter_path=cover_path,
        github_username=github_username.strip() or None,
        max_repos=max(1, min(max_repos, 30)),
    ))

    # A build with no claims means the one LLM call failed -- almost always an
    # exhausted Groq quota. Saving it produces a page that reads "Your Name /
    # Developer", which looks like a bug in the generator rather than a quota
    # that resets on its own. Fail with the reset time instead.
    if not result.graph.claims:
        shutil.rmtree(settings.upload_path / build_id, ignore_errors=True)
        detail = result.warnings[0] if result.warnings else "extraction produced nothing"
        raise HTTPException(503, detail)

    record = {
        "build_id": build_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "graph": result.graph.model_dump(mode="json"),
        "analytics": result.analytics,
        "repositories": result.repositories,
        "gallery": result.gallery,
        "metrics": result.metrics,
        "warnings": result.warnings,
        "theme": ThemeConfig().model_dump(),
    }
    _save(build_id, record)

    return JSONResponse({
        "build_id": build_id,
        "metrics": result.metrics,
        "warnings": result.warnings,
        "person": result.graph.person.model_dump(),
        "conflicts": [c.model_dump(mode="json") for c in result.graph.conflicts],
        "preview_url": f"/api/preview/{build_id}",
    })


@router.get("/profile/{build_id}")
def get_profile(build_id: str) -> dict[str, Any]:
    return _load(build_id)


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------


@router.get("/profile/{build_id}/provenance")
def provenance(build_id: str) -> dict[str, Any]:
    """Every generated sentence with the source spans behind it."""
    graph = _graph_of(_load(build_id))
    return {
        # page_sizes are in PDF points; the client scales boxes by
        # (image_width / page_width) to position overlays exactly.
        "documents": [d.model_dump() for d in graph.documents],
        "blocks": [
            {
                "target": b.target,
                "original": b.original,
                "published": b.published_text,
                "sentences": [
                    {
                        "text": s.text,
                        "source": s.primary_source,
                        "note": s.note,
                        "evidence": [
                            {
                                "source": e.source_id,
                                "text": e.short(300),
                                "locator": e.locator.model_dump(),
                            }
                            for e in s.evidence
                        ],
                    }
                    for s in b.sentences
                ],
            }
            for b in graph.blocks
        ],
    }


# ---------------------------------------------------------------------------
# gallery -- user-uploaded images only
# ---------------------------------------------------------------------------

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
IMAGE_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif", ".avif": "image/avif",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_GALLERY_IMAGES = 24


def _gallery_dir(build_id: str) -> Path:
    d = settings.upload_path / build_id / "gallery"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("/profile/{build_id}/gallery")
def list_gallery(build_id: str) -> dict[str, Any]:
    return {"gallery": _load(build_id).get("gallery") or []}


@router.post("/profile/{build_id}/gallery")
async def add_gallery_images(
    build_id: str,
    images: list[UploadFile] = File(...),
    captions: str = Form(""),
) -> dict[str, Any]:
    """Upload one or more images for the portfolio gallery.

    `captions` is an optional newline-separated list, positionally matched to
    the uploaded files. Images are stored on disk; only their metadata goes
    into the profile document.
    """
    record = _load(build_id)
    gallery: list[dict[str, Any]] = list(record.get("gallery") or [])

    if len(gallery) + len(images) > MAX_GALLERY_IMAGES:
        raise HTTPException(
            400,
            f"gallery holds at most {MAX_GALLERY_IMAGES} images "
            f"({len(gallery)} already uploaded)",
        )

    caption_list = [c.strip() for c in captions.split("\n")] if captions else []
    dest_dir = _gallery_dir(build_id)
    added: list[dict[str, Any]] = []

    for i, image in enumerate(images):
        suffix = Path(image.filename or "").suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            raise HTTPException(
                400,
                f"{image.filename!r}: unsupported image type "
                f"(allowed: {', '.join(sorted(IMAGE_SUFFIXES))})",
            )

        image_id = uuid.uuid4().hex[:10]
        dest = dest_dir / f"{image_id}{suffix}"

        size = 0
        with dest.open("wb") as out:
            while chunk := await image.read(1 << 20):
                size += len(chunk)
                if size > MAX_IMAGE_BYTES:
                    dest.unlink(missing_ok=True)
                    raise HTTPException(400, f"{image.filename!r} exceeds 5 MB")
                out.write(chunk)

        caption = caption_list[i] if i < len(caption_list) else ""
        added.append({
            "id": image_id,
            "filename": dest.name,
            "original_name": image.filename,
            "caption": caption or Path(image.filename or "").stem.replace("_", " "),
            "url": f"/api/profile/{build_id}/gallery/{dest.name}",
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        })

    gallery.extend(added)
    get_repository().update_fields(build_id, {"gallery": gallery})
    return {"ok": True, "added": len(added), "gallery": gallery}


@router.patch("/profile/{build_id}/gallery/{image_id}")
def update_caption(build_id: str, image_id: str, caption: str = Form(...)) -> dict[str, Any]:
    record = _load(build_id)
    gallery = list(record.get("gallery") or [])
    item = next((g for g in gallery if g["id"] == image_id), None)
    if item is None:
        raise HTTPException(404, f"unknown image {image_id}")
    item["caption"] = caption.strip()
    get_repository().update_fields(build_id, {"gallery": gallery})
    return {"ok": True, "image": item}


@router.delete("/profile/{build_id}/gallery/{image_id}")
def delete_gallery_image(build_id: str, image_id: str) -> dict[str, Any]:
    record = _load(build_id)
    gallery = list(record.get("gallery") or [])
    item = next((g for g in gallery if g["id"] == image_id), None)
    if item is None:
        raise HTTPException(404, f"unknown image {image_id}")

    (_gallery_dir(build_id) / item["filename"]).unlink(missing_ok=True)
    gallery = [g for g in gallery if g["id"] != image_id]
    get_repository().update_fields(build_id, {"gallery": gallery})
    return {"ok": True, "gallery": gallery}


@router.get("/profile/{build_id}/gallery/{filename}")
def gallery_image(build_id: str, filename: str) -> FileResponse:
    # Resolve inside the gallery directory so a crafted filename cannot walk out.
    base = _gallery_dir(build_id).resolve()
    path = (base / Path(filename).name).resolve()
    if not str(path).startswith(str(base)) or not path.exists():
        raise HTTPException(404, "image not found")
    return FileResponse(path, media_type=IMAGE_MIME.get(path.suffix.lower(), "image/png"))


@router.get("/profile/{build_id}/page/{source_id}/{page_no}")
def source_page_image(build_id: str, source_id: str, page_no: int, scale: float = 2.0) -> FileResponse:
    """Render one page of an uploaded PDF to PNG.

    The provenance viewer overlays absolutely-positioned boxes on this image.
    Rendering server-side with pypdfium2 avoids shipping a PDF engine to the
    browser, and the returned `page_size` from /provenance lets the client map
    PDF points to image pixels exactly.
    """
    import pypdfium2 as pdfium

    graph = _graph_of(_load(build_id))
    doc = next((d for d in graph.documents if d.source_id == source_id), None)
    if not doc or not doc.stored_path or not Path(doc.stored_path).exists():
        raise HTTPException(404, f"no stored document for source {source_id}")
    if not 0 <= page_no < doc.page_count:
        raise HTTPException(404, f"page {page_no} out of range (0..{doc.page_count - 1})")

    scale = max(1.0, min(scale, 4.0))
    out_dir = settings.cache_path / "pages" / build_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{source_id}-{page_no}@{scale:g}.png"

    if not out.exists():
        pdf = pdfium.PdfDocument(doc.stored_path)
        try:
            pdf[page_no].render(scale=scale).to_pil().save(out)
        finally:
            pdf.close()

    return FileResponse(out, media_type="image/png")


@router.get("/profile/{build_id}/source/{source_id}")
def source_document(build_id: str, source_id: str) -> FileResponse:
    """Serve an original upload so the viewer can draw boxes over it."""
    graph = _graph_of(_load(build_id))
    doc = next((d for d in graph.documents if d.source_id == source_id), None)
    if not doc or not doc.stored_path or not Path(doc.stored_path).exists():
        raise HTTPException(404, f"no stored document for source {source_id}")
    return FileResponse(doc.stored_path, media_type="application/pdf", filename=doc.filename)


# ---------------------------------------------------------------------------
# conflicts
# ---------------------------------------------------------------------------


class ResolveRequest(BaseModel):
    conflict_id: str
    value: str


@router.post("/profile/{build_id}/resolve")
def resolve_conflict(build_id: str, req: ResolveRequest) -> dict[str, Any]:
    record = _load(build_id)
    graph = _graph_of(record)

    conflict = next((c for c in graph.conflicts if c.id == req.conflict_id), None)
    if conflict is None:
        raise HTTPException(404, f"unknown conflict {req.conflict_id}")
    if req.value not in [o.value for o in conflict.options]:
        raise HTTPException(400, "value is not one of the offered options")

    conflict.resolved_value = req.value
    get_repository().update_fields(build_id, {"graph": graph.model_dump(mode="json")})
    return {"ok": True, "conflict": conflict.model_dump(mode="json")}


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


class RenderRequest(BaseModel):
    theme: ThemeConfig = ThemeConfig()


@router.post("/profile/{build_id}/theme")
def set_theme(build_id: str, req: RenderRequest) -> dict[str, Any]:
    theme = req.theme.model_dump()
    if not get_repository().update_fields(build_id, {"theme": theme}):
        raise HTTPException(404, f"unknown build id {build_id}")
    return {"ok": True, "theme": theme}


@router.get("/preview/{build_id}", response_class=HTMLResponse)
def preview(build_id: str) -> HTMLResponse:
    record = _load(build_id)
    graph = _graph_of(record)
    config = ThemeConfig.model_validate(record.get("theme") or {})
    html = render_portfolio(
        graph, config,
        analytics=record.get("analytics"),
        repositories=record.get("repositories"),
        gallery=record.get("gallery"),
        resume_url=f"/api/profile/{build_id}/source/resume",
    )
    return HTMLResponse(html)


@router.get("/export/{build_id}")
def export(build_id: str) -> FileResponse:
    """Download the portfolio as a deployable static site, zipped.

        index.html
        style.css
        script.js
        images/<gallery images>

    Separate files rather than one inlined page: this is what you drop onto
    Netlify, GitHub Pages or Vercel, and what a reviewer can actually read.
    """
    record = _load(build_id)
    graph = _graph_of(record)
    config = ThemeConfig.model_validate(record.get("theme") or {})
    gallery = record.get("gallery") or []

    files = render_bundle(
        graph, config,
        analytics=record.get("analytics"),
        repositories=record.get("repositories"),
        gallery=gallery,
    )

    out_dir = settings.cache_path / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = (graph.person.name or "portfolio").lower().replace(" ", "-")
    zip_path = out_dir / f"{slug}-{build_id}.zip"

    gdir = _gallery_dir(build_id)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text)

        for item in gallery:
            src = gdir / item["filename"]
            if src.exists():
                zf.write(src, f"images/{item['filename']}")

        zf.writestr("README.txt", _export_readme(graph, len(gallery)))

    return FileResponse(zip_path, media_type="application/zip", filename=zip_path.name)


def _export_readme(graph: ProfileGraph, image_count: int) -> str:
    return (
        f"{graph.person.name or 'Portfolio'} — generated by FolioProof\n"
        f"{'=' * 60}\n\n"
        "Contents\n"
        "  index.html   the page\n"
        "  style.css    theme and per-section colours\n"
        "  script.js    navigation and provenance mode\n"
        f"  images/      {image_count} gallery image(s)\n\n"
        "To view locally, open index.html in a browser.\n\n"
        "To publish, upload this folder to any static host — Netlify, GitHub\n"
        "Pages, Vercel or Cloudflare Pages. No build step and no server needed.\n\n"
        "Every sentence carries a data-provenance attribute naming the source\n"
        "document it came from. Run setProvenanceMode(true) in the browser\n"
        "console to highlight them.\n"
    )


@router.get("/profiles")
def list_profiles(limit: int = 20) -> dict[str, Any]:
    """Recent builds, newest first."""
    return {
        "storage": get_repository().backend,
        "profiles": get_repository().list_recent(max(1, min(limit, 50))),
    }


@router.delete("/profile/{build_id}")
def delete_profile(build_id: str) -> dict[str, bool]:
    get_repository().delete(build_id)
    shutil.rmtree(settings.upload_path / build_id, ignore_errors=True)
    return {"ok": True}
