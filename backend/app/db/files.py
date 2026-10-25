"""Binary storage for uploaded PDFs and gallery images.

Why this exists: MongoDB holds the *metadata*, but a résumé PDF and a gallery
photo are bytes on a disk. On a laptop that disk is permanent. On Render,
Railway, Fly (without a volume) or Cloud Run it is **ephemeral** — every
redeploy, restart or idle spin-down wipes it.

That failure is quiet and late. The Mongo records survive, still pointing at
paths that no longer exist, so the app deploys fine and then breaks the first
time the instance restarts: résumé download 404s, the provenance viewer has no
page to draw boxes on, gallery images vanish.

So in production the files live in GridFS, inside the same Atlas cluster that
already holds the metadata. No extra service, no extra credentials. GridFS
chunks its payloads, so the 16 MB BSON document limit does not apply.

Local disk remains the fallback when Mongo is unreachable, mirroring
`ProfileRepository`, so development without a database still works.

References are self-describing strings:

    gridfs:<objectid>          stored in GridFS
    file:<path>                stored on local disk
    <bare path>                legacy record written before this module
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

import gridfs
from bson import ObjectId
from bson.errors import InvalidId
from pymongo import MongoClient
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

from app.config import settings

log = logging.getLogger(__name__)

GRIDFS_PREFIX = "gridfs:"
FILE_PREFIX = "file:"


class FileStore:
    """Durable storage for build artefacts."""

    BUCKET = "uploads"

    def __init__(self, uri: str | None = None, db_name: str | None = None,
                 fallback_dir: Path | None = None):
        self.uri = uri or settings.mongodb_uri
        self.db_name = db_name or settings.mongodb_db
        self.fallback_dir = fallback_dir or settings.upload_path

        self._client: MongoClient | None = None
        self._fs: gridfs.GridFS | None = None
        self.connected = False
        self._connect()

    def _connect(self) -> None:
        try:
            client: MongoClient = MongoClient(
                self.uri,
                serverSelectionTimeoutMS=settings.mongodb_timeout_ms,
                appname="folioproof-files",
            )
            client.admin.command("ping")
            self._client = client
            self._fs = gridfs.GridFS(client[self.db_name], collection=self.BUCKET)
            self.connected = True
            log.info("GridFS ready in %s.%s", self.db_name, self.BUCKET)
        except (ServerSelectionTimeoutError, PyMongoError) as exc:
            log.warning(
                "GridFS unavailable (%s) — falling back to local disk at %s. "
                "On an ephemeral host these files WILL be lost on restart.",
                type(exc).__name__, self.fallback_dir,
            )
            self.connected = False

    @property
    def backend(self) -> str:
        return "gridfs" if self.connected else "local-disk"

    # -- writing -----------------------------------------------------------

    def put(self, build_id: str, label: str, filename: str, data: bytes,
            content_type: str = "application/octet-stream") -> str:
        """Store bytes and return a reference to them."""
        if self.connected and self._fs is not None:
            try:
                oid = self._fs.put(
                    data,
                    filename=filename,
                    contentType=content_type,
                    metadata={"build_id": build_id, "label": label},
                )
                return f"{GRIDFS_PREFIX}{oid}"
            except PyMongoError as exc:
                log.error("GridFS write failed for %s/%s (%s); using disk",
                          build_id, label, exc)
                self.connected = False

        dest = self.fallback_dir / build_id / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return f"{FILE_PREFIX}{dest}"

    # -- reading -----------------------------------------------------------

    def read(self, ref: str | None) -> bytes | None:
        """Resolve a reference to bytes, whatever kind of reference it is."""
        if not ref:
            return None

        if ref.startswith(GRIDFS_PREFIX):
            if not self.connected or self._fs is None:
                log.error("cannot read %s: GridFS not connected", ref)
                return None
            try:
                return self._fs.get(ObjectId(ref[len(GRIDFS_PREFIX):])).read()
            except (gridfs.NoFile, InvalidId, PyMongoError) as exc:
                log.error("GridFS read failed for %s (%s)", ref, exc)
                return None

        # file: prefixed, or a legacy bare path from before this module
        path = Path(ref[len(FILE_PREFIX):] if ref.startswith(FILE_PREFIX) else ref)
        return path.read_bytes() if path.exists() else None

    def exists(self, ref: str | None) -> bool:
        if not ref:
            return False
        if ref.startswith(GRIDFS_PREFIX):
            if not self.connected or self._fs is None:
                return False
            try:
                return self._fs.exists(ObjectId(ref[len(GRIDFS_PREFIX):]))
            except (InvalidId, PyMongoError):
                return False
        path = Path(ref[len(FILE_PREFIX):] if ref.startswith(FILE_PREFIX) else ref)
        return path.exists()

    # -- deleting ----------------------------------------------------------

    def delete(self, ref: str | None) -> None:
        if not ref:
            return
        if ref.startswith(GRIDFS_PREFIX):
            if self.connected and self._fs is not None:
                try:
                    self._fs.delete(ObjectId(ref[len(GRIDFS_PREFIX):]))
                except (InvalidId, PyMongoError) as exc:
                    log.error("GridFS delete failed for %s (%s)", ref, exc)
            return
        path = Path(ref[len(FILE_PREFIX):] if ref.startswith(FILE_PREFIX) else ref)
        path.unlink(missing_ok=True)

    def delete_build(self, build_id: str) -> int:
        """Remove every file belonging to a build. Returns how many were removed."""
        removed = 0
        if self.connected and self._fs is not None:
            try:
                for f in self._fs.find({"metadata.build_id": build_id}):
                    self._fs.delete(f._id)
                    removed += 1
            except PyMongoError as exc:
                log.error("GridFS bulk delete failed for %s (%s)", build_id, exc)
        shutil.rmtree(self.fallback_dir / build_id, ignore_errors=True)
        return removed

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


_store: FileStore | None = None


def get_file_store() -> FileStore:
    global _store
    if _store is None:
        _store = FileStore()
    return _store
