"""HTTP surface.

Profiles are persisted in MongoDB via `ProfileRepository`. A build record is a
single document -- the ProfileGraph dumped straight to JSON -- which is why a
document store suits this shape better than tables would.
"""
from __future__ import annotations

import base64
import logging
import io

import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from app.config import settings
from app.db.files import get_file_store
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

def _read_upload(file: UploadFile, label: str) -> bytes:
    """Read an uploaded PDF into memory, enforcing type and size."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"{label}: only PDF uploads are supported (got {suffix or 'none'})")

    data = b""
    while chunk := file.file.read(1 << 20):
        data += chunk
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, f"{label}: file exceeds 10 MB")
    if not data:
        raise HTTPException(400, f"{label}: file is empty")
    return data

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
    store = get_file_store()

    sources: dict[str, bytes] = {"resume": _read_upload(resume, "resume")}
    if linkedin:
        sources["linkedin"] = _read_upload(linkedin, "linkedin")
    if cover_letter:
        sources["cover_letter"] = _read_upload(cover_letter, "cover_letter")

    # The pipeline reads PDFs from paths, so stage them in a temp directory for
    # the duration of the build. Durable storage happens afterwards -- nothing
    # is persisted for a build that fails.
    with tempfile.TemporaryDirectory(prefix=f"folioproof-{build_id}-") as tmp:
        staged = {}
        for label, data in sources.items():
            path = Path(tmp) / f"{label}.pdf"
            path.write_bytes(data)
            staged[label] = path

        try:
            result = build_profile(BuildInputs(
                resume_path=staged["resume"],
                linkedin_path=staged.get("linkedin"),
                cover_letter_path=staged.get("cover_letter"),
                github_username=github_username.strip() or None,
                max_repos=max(1, min(max_repos, 30)),
            ))
        except ValueError as exc:
            # parse_pdf raises this on a scanned/empty résumé — surface a
            # clean 400 rather than a 500 with a stack trace.
            raise HTTPException(400, f"résumé: {exc}") from exc
        except Exception as exc:
            log.exception("build_profile crashed for %s", build_id)
            raise HTTPException(
                500,
                f"Build failed unexpectedly: {type(exc).__name__}. "
                "The server logs have the details.",
            ) from exc

        # A build with no claims means every fallback in the extraction ladder
        # failed — usually an exhausted Groq daily quota, an invalid API key,
        # or a résumé the parser could not read. Fail with a friendly reason
        # rather than saving a page that reads "Your Name / Developer".
        if not result.graph.claims:
            detail = result.warnings[0] if result.warnings else (
                "We couldn't extract anything from your documents. "
                "Check that your résumé is a text-based (not scanned) PDF, "
                "and that the backend has a valid GROQ_API_KEY."
            )
            raise HTTPException(503, detail)

        # Persist the originals somewhere that survives a restart, and rewrite
        # each document's pointer from the temp path to that reference. If the
        # file store is unreachable we log and continue — the profile is still
        # usable, just without downloadable originals.
        for doc in result.graph.documents:
            data = sources.get(doc.source_id)
            if data is None:
                continue
            try:
                doc.stored_path = store.put(
                    build_id, doc.source_id, f"{doc.source_id}.pdf",
                    data, "application/pdf",
                )
            except Exception as exc:
                log.error("failed to persist %s for %s: %s", doc.source_id, build_id, exc)
                result.warnings.append(
                    f"Could not archive the {doc.source_id} PDF; "
                    "the download link and provenance overlay will be unavailable."
                )

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
    try:
        _save(build_id, record)
    except Exception as exc:
        log.exception("failed to persist build %s", build_id)
        raise HTTPException(
            500, f"Build succeeded but could not be saved: {type(exc).__name__}"
        ) from exc

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
    store = get_file_store()
    added: list[dict[str, Any]] = []

    for i, image in enumerate(images):
        suffix = Path(image.filename or "").suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            raise HTTPException(
                400,
                f"{image.filename!r}: unsupported image type "
                f"(allowed: {', '.join(sorted(IMAGE_SUFFIXES))})",
            )

        data = b""
        while chunk := await image.read(1 << 20):
            data += chunk
            if len(data) > MAX_IMAGE_BYTES:
                raise HTTPException(400, f"{image.filename!r} exceeds 5 MB")

        image_id = uuid.uuid4().hex[:10]
        filename = f"{image_id}{suffix}"
        ref = store.put(
            build_id, "gallery", filename, data,
            IMAGE_MIME.get(suffix, "image/png"),
        )

        caption = caption_list[i] if i < len(caption_list) else ""
        added.append({
            "id": image_id,
            "filename": filename,
            "ref": ref,
            "original_name": image.filename,
            "caption": caption or Path(image.filename or "").stem.replace("_", " "),
            "url": f"/api/profile/{build_id}/gallery/{filename}",
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

    get_file_store().delete(item.get("ref") or str(_gallery_dir(build_id) / item["filename"]))
    gallery = [g for g in gallery if g["id"] != image_id]
    get_repository().update_fields(build_id, {"gallery": gallery})
    return {"ok": True, "gallery": gallery}

@router.get("/profile/{build_id}/gallery/{filename}")
def gallery_image(build_id: str, filename: str) -> Response:
    """Serve a gallery image from wherever it is stored."""
    safe = Path(filename).name          # never let a crafted name walk out
    item = next(
        (g for g in (_load(build_id).get("gallery") or []) if g["filename"] == safe),
        None,
    )
    if item is None:
        raise HTTPException(404, "image not found")

    # Older records predate `ref` and stored files on disk by path.
    ref = item.get("ref") or str(_gallery_dir(build_id) / safe)
    data = get_file_store().read(ref)
    if data is None:
        raise HTTPException(404, "image not found")

    return Response(
        content=data,
        media_type=IMAGE_MIME.get(Path(safe).suffix.lower(), "image/png"),
        headers={"Cache-Control": "public, max-age=86400"},
    )

@router.get("/profile/{build_id}/page/{source_id}/{page_no}")
def source_page_image(build_id: str, source_id: str, page_no: int, scale: float = 2.0) -> Response:
    """Render one page of a stored PDF to PNG.

    The provenance viewer overlays absolutely-positioned boxes on this image.
    Rendering server-side with pypdfium2 avoids shipping a PDF engine to the
    browser, and the `page_sizes` returned by /provenance let the client map
    PDF points to image pixels exactly.
    """
    import pypdfium2 as pdfium

    graph = _graph_of(_load(build_id))
    doc = next((d for d in graph.documents if d.source_id == source_id), None)
    if doc is None:
        raise HTTPException(404, f"no stored document for source {source_id}")
    if not 0 <= page_no < doc.page_count:
        raise HTTPException(404, f"page {page_no} out of range (0..{doc.page_count - 1})")

    data = get_file_store().read(doc.stored_path)
    if data is None:
        raise HTTPException(404, f"source file for {source_id} is no longer available")

    scale = max(1.0, min(scale, 4.0))
    buf = io.BytesIO()
    pdf = pdfium.PdfDocument(data)
    try:
        pdf[page_no].render(scale=scale).to_pil().save(buf, format="PNG")
    finally:
        pdf.close()

    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )

@router.get("/profile/{build_id}/source/{source_id}")
def source_document(build_id: str, source_id: str) -> Response:
    """Serve an original upload (the "Download résumé" link)."""
    graph = _graph_of(_load(build_id))
    doc = next((d for d in graph.documents if d.source_id == source_id), None)
    if doc is None:
        raise HTTPException(404, f"no stored document for source {source_id}")

    data = get_file_store().read(doc.stored_path)
    if data is None:
        raise HTTPException(404, f"source file for {source_id} is no longer available")

    name = doc.filename or f"{source_id}.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )

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
        analytics = record.get("analytics"),
        repositories = record.get("repositories"),
        gallery = record.get("gallery"),
        resume_url = f"/api/profile/{build_id}/source/resume",
    )
    return HTMLResponse(html)

@router.get("/export/{build_id}")
def export(build_id: str) -> Response:
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
        analytics = record.get("analytics"),
        repositories = record.get("repositories"),
        gallery = gallery,
    )

    # Built in memory: an ephemeral host has nowhere durable to put a temp file,
    # and the zip is disposable the moment it is streamed to the browser.
    store = get_file_store()
    slug = (graph.person.name or "portfolio").lower().replace(" ", "-")
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text)

        shipped = 0
        for item in gallery:
            ref = item.get("ref") or str(_gallery_dir(build_id) / item["filename"])
            data = store.read(ref)
            if data is not None:
                zf.writestr(f"images/{item['filename']}", data)
                shipped += 1

        zf.writestr("README.txt", _export_readme(graph, shipped))

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}-{build_id}.zip"'},
    )

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
def delete_profile(build_id: str) -> dict[str, Any]:
    """Remove a build: its record, and every file belonging to it."""
    removed = get_file_store().delete_build(build_id)
    get_repository().delete(build_id)
    return {"ok": True, "files_removed": removed}