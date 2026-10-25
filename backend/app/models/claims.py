"""Core data model for FolioProof.

The central invariant of this project lives here:

    A Claim cannot exist without at least one piece of Evidence.

`Claim.evidence` is declared with ``min_length=1``, so Pydantic rejects any
attempt to construct a claim that is not anchored to something the user
actually supplied. Everything downstream -- fusion, rewriting, verification,
rendering -- operates on Claims, which means a fabricated fact has no
representable form anywhere in the pipeline.
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

def _new_id() -> str:
    return uuid.uuid4().hex[:12]

# ---------------------------------------------------------------------------
# Source locators -- where a piece of evidence physically lives
# ---------------------------------------------------------------------------

SourceId = Literal["resume", "github", "linkedin", "cover_letter"]

class PDFSpan(BaseModel):
    """A rectangle on a page of an uploaded PDF.

    pdfplumber gives word-level coordinates, which is what makes the provenance
    viewer possible: we can draw this box over the rendered page and show the
    user exactly which words support a generated sentence.
    """

    kind: Literal["pdf"] = "pdf"
    page: int = Field(ge = 0, description = "0-indexed page number")
    x0: float
    top: float
    x1: float
    bottom: float
    line_index: int | None = None

    def as_box(self) -> tuple[float, float, float, float]:
        return (self.x0, self.top, self.x1, self.bottom)

    def merge(self, other: "PDFSpan") -> "PDFSpan":
        """Union of two spans on the same page (used to cover a whole line)."""
        if other.page != self.page:
            return self
        return PDFSpan(
            page = self.page,
            x0 = min(self.x0, other.x0),
            top = min(self.top, other.top),
            x1 = max(self.x1, other.x1),
            bottom = max(self.bottom, other.bottom),
            line_index = self.line_index,
        )

class GitHubField(BaseModel):
    """A specific field of a specific GitHub resource."""

    kind: Literal["github"] = "github"
    repo: str | None = None          # "owner/name", None for profile-level facts
    field: str                       # description | readme | language | topics | stars ...
    url: str | None = None

class TextSpan(BaseModel):
    """A character range inside a plain-text or DOCX source."""

    kind: Literal["text"] = "text"
    start: int = Field(ge = 0)
    end: int = Field(ge = 0)
    section: str | None = None

Locator = Annotated[
    Union[PDFSpan, GitHubField, TextSpan],
    Field(discriminator = "kind"),
]

class Evidence(BaseModel):
    """One concrete justification for a claim."""

    model_config = ConfigDict(frozen = True)

    source_id: SourceId
    locator: Locator
    raw_text: str = Field(min_length = 1)

    def short(self, limit: int = 160) -> str:
        t = " ".join(self.raw_text.split())
        return t if len(t) <= limit else t[: limit - 1] + "…"

# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

class ClaimKind(str, Enum):
    SKILL = "skill"
    PROJECT = "project"
    ROLE = "role"
    EDUCATION = "education"
    ACHIEVEMENT = "achievement"
    CERTIFICATION = "certification"
    CONTACT = "contact"
    SUMMARY = "summary"

class Claim(BaseModel):
    """An atomic professional fact, permanently bound to its evidence."""

    id: str = Field(default_factory = _new_id)
    kind: ClaimKind
    value: str = Field(min_length = 1, description = "Canonical short form, e.g. 'FastAPI'")
    attributes: dict[str, Any] = Field(default_factory = dict)

    # The invariant. Do not relax this.
    evidence: list[Evidence] = Field(min_length=1)

    confidence: float = Field(default = 1.0, ge = 0.0, le = 1.0)

    @field_validator("value")
    @classmethod
    def _strip_value(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("claim value cannot be blank")
        return v

    @property
    def sources(self) -> set[str]:
        return {e.source_id for e in self.evidence}

    @property
    def corroboration(self) -> int:
        """How many distinct sources back this claim. Used as a strength signal."""
        return len(self.sources)

    @property
    def primary_source(self) -> str | None:
        """The most authoritative source backing this claim."""
        from app.fusion.priority import best_source

        return best_source(self.sources)

    def merged_with(self, other: "Claim") -> "Claim":
        """Combine a duplicate claim from another source into this one.

        Delegates to the precedence rules so the higher-priority source
        (resume > linkedin > github > cover_letter) wins on conflicting values,
        while evidence from every source is retained for corroboration.
        """
        from app.fusion.priority import merge_by_priority

        return merge_by_priority([self, other])

# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------

class ConflictOption(BaseModel):
    value: str
    evidence: Evidence

class Conflict(BaseModel):
    """A disagreement between sources that the user must resolve."""

    id: str = Field(default_factory = _new_id)
    field: str                       # "graduation_year", "job_title:Acme", ...
    description: str
    options: list[ConflictOption] = Field(min_length = 2)
    resolved_value: str | None = None

    @property
    def is_resolved(self) -> bool:
        return self.resolved_value is not None

class Gap(BaseModel):
    """Something present in one source but absent from another.

    Not a contradiction -- an omission worth surfacing (e.g. a substantial
    GitHub repo that never made it onto the resume).
    """

    id: str = Field(default_factory = _new_id)
    kind: str                        # "missing_from_resume", "missing_from_github"
    description: str
    claim_id: str | None = None

# ---------------------------------------------------------------------------
# Generated text + verification
# ---------------------------------------------------------------------------

class GeneratedSentence(BaseModel):
    """One sentence of portfolio copy, traceable back to the claims behind it."""

    text: str
    claim_ids: list[str] = Field(default_factory = list)
    evidence: list[Evidence] = Field(default_factory = list)
    note: str | None = None

    @property
    def primary_source(self) -> str | None:
        """Most authoritative source backing this sentence."""
        from app.fusion.priority import best_source

        return best_source(e.source_id for e in self.evidence)

class EnhancedBlock(BaseModel):
    """A rewritten passage (project description, bio, ...) plus its audit trail."""

    target: str                       # "bio" | "project:<claim_id>" | ...
    original: str
    sentences: list[GeneratedSentence] = Field(default_factory=list)

    @property
    def published_text(self) -> str:
        return " ".join(s.text for s in self.sentences)

# ---------------------------------------------------------------------------
# The aggregate
# ---------------------------------------------------------------------------

class PersonInfo(BaseModel):
    name: str | None = None
    headline: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: dict[str, str] = Field(default_factory=dict)

class SourceDocument(BaseModel):
    """A file the user gave us, kept so the provenance viewer can render it."""

    source_id: SourceId
    filename: str | None = None
    stored_path: str | None = None
    page_count: int = 0
    page_sizes: list[tuple[float, float]] = Field(default_factory=list)

class ProfileGraph(BaseModel):
    """The fused, non-contradictory profile assembled from every source."""

    person: PersonInfo = Field(default_factory = PersonInfo)
    claims: list[Claim] = Field(default_factory = list)
    conflicts: list[Conflict] = Field(default_factory = list)
    gaps: list[Gap] = Field(default_factory = list)
    documents: list[SourceDocument] = Field(default_factory = list)
    blocks: list[EnhancedBlock] = Field(default_factory = list)

    def by_kind(self, kind: ClaimKind) -> list[Claim]:
        return [c for c in self.claims if c.kind is kind]

    def claim(self, claim_id: str) -> Claim | None:
        return next((c for c in self.claims if c.id == claim_id), None)

    def stats(self) -> dict[str, Any]:
        return {
            "claims": len(self.claims),
            "by_kind": {k.value: len(self.by_kind(k)) for k in ClaimKind},
            "multi_source_claims": sum(1 for c in self.claims if c.corroboration > 1),
            "conflicts": len(self.conflicts),
            "auto_resolved_conflicts": sum(1 for c in self.conflicts if c.is_resolved),
            "gaps": len(self.gaps),
        }