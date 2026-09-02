"""MongoDB persistence for built profiles.

The stored document *is* the Pydantic model — `ProfileGraph.model_dump(mode="json")`
round-trips cleanly through BSON, so there is no ORM layer and no schema
migration story. That is the reason a document store fits this project: a
profile is a deeply nested tree of claims, each carrying a variable-shaped
locator, and flattening that into relational tables would buy nothing.

If no MongoDB server is reachable the repository degrades to JSON files on
disk and says so loudly. That keeps the app usable before Mongo is set up
without silently pretending writes succeeded.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pymongo import ASCENDING, MongoClient
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

from app.config import settings

log = logging.getLogger(__name__)


class ProfileRepository:
    """Storage for build records, backed by MongoDB when one is available."""

    COLLECTION = "profiles"

    def __init__(self, uri: str | None = None, db_name: str | None = None,
                 fallback_dir: Path | None = None):
        self.uri = uri or settings.mongodb_uri
        self.db_name = db_name or settings.mongodb_db
        self.fallback_dir = fallback_dir or (settings.cache_path / "profiles")
        self.fallback_dir.mkdir(parents=True, exist_ok=True)

        self._client: MongoClient | None = None
        self._collection = None
        self.connected = False
        self._connect()

    # -- connection --------------------------------------------------------

    def _connect(self) -> None:
        try:
            client: MongoClient = MongoClient(
                self.uri,
                serverSelectionTimeoutMS=settings.mongodb_timeout_ms,
                appname="folioproof",
            )
            client.admin.command("ping")          # forces a real round-trip
            collection = client[self.db_name][self.COLLECTION]
            collection.create_index([("build_id", ASCENDING)], unique=True)
            collection.create_index([("created_at", ASCENDING)])

            self._client = client
            self._collection = collection
            self.connected = True
            log.info("MongoDB connected: %s/%s", self._safe_uri(), self.db_name)
        except (ServerSelectionTimeoutError, PyMongoError) as exc:
            log.warning(
                "MongoDB unreachable (%s) — falling back to JSON files at %s. "
                "Set MONGODB_URI in backend/.env to use a real database.",
                type(exc).__name__, self.fallback_dir,
            )
            self.connected = False

    def _safe_uri(self) -> str:
        """URI with any credentials stripped, safe to log."""
        uri = self.uri
        if "@" in uri:
            scheme, _, rest = uri.partition("://")
            return f"{scheme}://***@{rest.split('@', 1)[1]}"
        return uri

    @property
    def backend(self) -> str:
        return "mongodb" if self.connected else "json-files"

    # -- fallback helpers --------------------------------------------------

    def _file(self, build_id: str) -> Path:
        return self.fallback_dir / f"{build_id}.json"

    # -- CRUD --------------------------------------------------------------

    def save(self, build_id: str, record: dict[str, Any]) -> None:
        record = {**record, "build_id": build_id}
        if self.connected and self._collection is not None:
            try:
                self._collection.replace_one(
                    {"build_id": build_id}, record, upsert=True
                )
                return
            except PyMongoError as exc:
                log.error("Mongo write failed for %s (%s); writing to disk", build_id, exc)
                self.connected = False
        self._file(build_id).write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8"
        )

    def get(self, build_id: str) -> dict[str, Any] | None:
        if self.connected and self._collection is not None:
            try:
                doc = self._collection.find_one(
                    {"build_id": build_id}, {"_id": False}
                )
                if doc is not None:
                    return doc
            except PyMongoError as exc:
                log.error("Mongo read failed for %s (%s); trying disk", build_id, exc)

        path = self._file(build_id)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def update_fields(self, build_id: str, fields: dict[str, Any]) -> bool:
        if self.connected and self._collection is not None:
            try:
                res = self._collection.update_one(
                    {"build_id": build_id}, {"$set": fields}
                )
                if res.matched_count:
                    return True
            except PyMongoError as exc:
                log.error("Mongo update failed for %s (%s)", build_id, exc)

        record = self.get(build_id)
        if record is None:
            return False
        record.update(fields)
        self._file(build_id).write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8"
        )
        return True

    def delete(self, build_id: str) -> None:
        if self.connected and self._collection is not None:
            try:
                self._collection.delete_one({"build_id": build_id})
            except PyMongoError as exc:
                log.error("Mongo delete failed for %s (%s)", build_id, exc)
        self._file(build_id).unlink(missing_ok=True)

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        if self.connected and self._collection is not None:
            try:
                cursor = (
                    self._collection.find(
                        {}, {"_id": False, "build_id": True, "created_at": True,
                             "graph.person.name": True, "metrics.claims": True}
                    )
                    .sort("created_at", -1)
                    .limit(limit)
                )
                return list(cursor)
            except PyMongoError as exc:
                log.error("Mongo list failed (%s)", exc)

        files = sorted(
            self.fallback_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]
        out = []
        for f in files:
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                out.append({
                    "build_id": d.get("build_id", f.stem),
                    "created_at": d.get("created_at"),
                    "graph": {"person": {"name": d.get("graph", {}).get("person", {}).get("name")}},
                    "metrics": {"claims": d.get("metrics", {}).get("claims")},
                })
            except (json.JSONDecodeError, OSError):
                continue
        return out

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


_repo: ProfileRepository | None = None


def get_repository() -> ProfileRepository:
    global _repo
    if _repo is None:
        _repo = ProfileRepository()
    return _repo
