"""PDF ingestion that preserves *where* every word came from.

This is the reason the project uses pdfplumber rather than PyPDF2. PyPDF2
returns a flat string; pdfplumber returns each word with its bounding box.
Keeping those coordinates all the way through the pipeline is what lets the
UI highlight the exact region of the original document that supports a
generated sentence.

The extractor produces `TextLine` objects (text + merged bbox + page), groups
them into `Section`s using heading heuristics, and can hand back a `PDFSpan`
for any line so it can be attached to a Claim as Evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from app.models.claims import PDFSpan

# Headings we expect in resumes and LinkedIn exports. Matching is done on a
# normalised (lowercased, punctuation-stripped) form of the line.
SECTION_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("summary", ("summary", "professional summary", "objective", "profile", "about", "about me")),
    ("experience", ("experience", "work experience", "professional experience",
                    "employment", "employment history", "internships", "internship")),
    ("education", ("education", "academics", "academic background", "qualifications")),
    ("skills", ("skills", "technical skills", "core skills", "technologies",
                "skills and interests", "top skills")),
    ("projects", ("projects", "personal projects", "academic projects", "key projects",
                  "selected projects")),
    ("certifications", ("certifications", "certificates", "licenses & certifications",
                        "licenses and certifications", "courses")),
    ("achievements", ("achievements", "awards", "honors", "honours", "accomplishments",
                      "awards & achievements", "extra curricular", "extracurricular")),
    ("publications", ("publications", "research", "papers", "research papers")),
    ("contact", ("contact", "contact information", "personal details")),
]

_NORMALISE_RE = re.compile(r"[^a-z& ]+")
_BULLET_RE = re.compile(r"^\s*[•‣▪●·⁃\-\*–—]\s*")
# Some PDFs embed glyphs with no Unicode mapping; pdfplumber surfaces those as
# "(cid:NNN)". They are almost always bullets or dingbats, so drop them.
_CID_RE = re.compile(r"\(cid:\d+\)")

def _normalise_heading(text: str) -> str:
    return _NORMALISE_RE.sub("", text.lower()).strip()

def _contains(haystack: str, needle: str) -> bool:
    """Substring test that respects token boundaries for short needles.

    Without this, the skill "Git" matches inside "github.com/someone" and the
    provenance box points at a contact line instead of the skills line. Plain
    ``\\b`` is not usable because real skill names end in punctuation ("C++",
    "Node.js"), so boundaries are checked against adjacent characters directly.
    """
    if not needle or not haystack:
        return False
    if len(needle) > 6 and " " in needle:
        return needle in haystack

    start = 0
    while (idx := haystack.find(needle, start)) != -1:
        before = haystack[idx - 1] if idx > 0 else " "
        after_i = idx + len(needle)
        after = haystack[after_i] if after_i < len(haystack) else " "
        if not before.isalnum() and not after.isalnum():
            return True
        start = idx + 1
    return False

@dataclass
class TextLine:
    """One visual line of the document, with its position on the page."""

    text: str
    page: int
    x0: float
    top: float
    x1: float
    bottom: float
    index: int
    size: float = 0.0
    bold: bool = False

    def span(self) -> PDFSpan:
        return PDFSpan(
            page = self.page,
            x0 = self.x0,
            top = self.top,
            x1 = self.x1,
            bottom = self.bottom,
            line_index = self.index,
        )

    @property
    def is_bullet(self) -> bool:
        stripped = _CID_RE.sub("", self.text).strip()
        return bool(_BULLET_RE.match(self.text)) or _CID_RE.match(self.text.strip()) is not None or (
            stripped != self.text.strip() and bool(stripped)
        )

    @property
    def clean(self) -> str:
        text = _CID_RE.sub(" ", self.text)
        return _BULLET_RE.sub("", " ".join(text.split())).strip()

@dataclass
class Section:
    name: str
    heading_line: TextLine | None
    lines: list[TextLine] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.clean for line in self.lines if line.clean)

    def span_for(self, needle: str) -> PDFSpan | None:
        """Find the line that best contains `needle` and return its box."""
        target = " ".join(needle.lower().split())
        if not target:
            return None
        best: tuple[float, TextLine] | None = None
        for line in self.lines:
            hay = " ".join(line.clean.lower().split())
            if not hay:
                continue
            if target in hay or hay in target:
                score = len(hay) and min(len(hay), len(target)) / max(len(hay), len(target))
                if best is None or score > best[0]:
                    best = (score, line)
        return best[1].span() if best else None

@dataclass
class ParsedPDF:
    path: str
    page_count: int
    page_sizes: list[tuple[float, float]]
    lines: list[TextLine]
    sections: dict[str, Section]

    @property
    def full_text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    def section_text(self, name: str) -> str:
        sec = self.sections.get(name)
        return sec.text if sec else ""

    def find_line(self, needle: str) -> TextLine | None:
        """Locate the line `needle` came from.

        Tries exact containment first, then falls back to token overlap so that
        an LLM-normalised value ("B.Tech Information Technology") still resolves
        to the line it was derived from ("B.Tech (Information Technology)").
        """
        target = " ".join(needle.lower().split())
        if not target:
            return None

        for line in self.lines:
            hay = " ".join(line.clean.lower().split())
            if hay and (_contains(hay, target) or _contains(target, hay)):
                return line

        target_tokens = {t for t in re.findall(r"[a-z0-9+#.]+", target) if len(t) > 2}
        if not target_tokens:
            return None

        best_score, best_line = 0.0, None
        for line in self.lines:
            hay_tokens = {t for t in re.findall(r"[a-z0-9+#.]+", line.clean.lower()) if len(t) > 2}
            if not hay_tokens:
                continue
            overlap = len(target_tokens & hay_tokens) / len(target_tokens)
            if overlap > best_score:
                best_score, best_line = overlap, line

        return best_line if best_line and best_score >= 0.5 else None

    def find_span(self, needle: str) -> PDFSpan | None:
        """Bounding box of the line `needle` came from, if it can be located."""
        line = self.find_line(needle)
        return line.span() if line else None

def _lines_from_page(page: pdfplumber.page.Page, page_no: int, start_index: int) -> list[TextLine]:
    """Group pdfplumber words into visual lines, merging their bounding boxes."""
    words = page.extract_words(
        use_text_flow = False,
        keep_blank_chars = False,
        extra_attrs = ["size", "fontname"],
    )
    if not words:
        return []

    # Bucket words by their vertical position. A tolerance of half the median
    # word height keeps superscripts and slight baseline drift on one line.
    heights = sorted(w["bottom"] - w["top"] for w in words)
    median_h = heights[len(heights) // 2] or 10.0
    tol = max(median_h * 0.6, 2.0)

    buckets: list[list[dict]] = []
    for w in sorted(words, key = lambda w: (round(w["top"], 1), w["x0"])):
        placed = False
        for bucket in buckets:
            if abs(bucket[0]["top"] - w["top"]) <= tol:
                bucket.append(w)
                placed = True
                break
        if not placed:
            buckets.append([w])

    lines: list[TextLine] = []
    for i, bucket in enumerate(buckets):
        bucket.sort(key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in bucket).strip()
        if not text:
            continue
        fontnames = " ".join(str(w.get("fontname", "")) for w in bucket).lower()
        lines.append(
            TextLine(
                text = text,
                page = page_no,
                x0 = min(w["x0"] for w in bucket),
                top = min(w["top"] for w in bucket),
                x1 = max(w["x1"] for w in bucket),
                bottom = max(w["bottom"] for w in bucket),
                index = start_index + i,
                size = max(float(w.get("size", 0) or 0) for w in bucket),
                bold = ("bold" in fontnames or "black" in fontnames or "semib" in fontnames),
            )
        )
    return lines

def _looks_like_heading(line: TextLine, body_size: float) -> bool:
    text = line.clean
    if not text or len(text) > 60:
        return False
    words = text.split()
    if len(words) > 6:
        return False
    if line.is_bullet:
        return False
    bigger = line.size > body_size + 0.4
    shouty = text.isupper() and len(text) > 2
    return bool(line.bold or bigger or shouty)

def _segment_sections(lines: list[TextLine]) -> dict[str, Section]:
    """Split the document into named sections using heading heuristics."""
    if not lines:
        return {}

    sizes = sorted(l.size for l in lines if l.size)
    body_size = sizes[len(sizes) // 2] if sizes else 0.0

    known: dict[str, tuple[str, ...]] = {}
    for canonical, variants in SECTION_PATTERNS:
        for v in variants:
            known[v] = canonical  # type: ignore[assignment]

    sections: dict[str, Section] = {}
    current = Section(name="header", heading_line=None)
    sections["header"] = current

    for line in lines:
        norm = _normalise_heading(line.clean)
        canonical = known.get(norm)

        # Only treat it as a section break if it both matches a known heading
        # *and* looks visually like a heading (or is a bare one-word heading).
        if canonical and (_looks_like_heading(line, body_size) or len(norm.split()) <= 2):
            if canonical in sections:
                current = sections[canonical]
                current.heading_line = current.heading_line or line
            else:
                current = Section(name=canonical, heading_line=line)
                sections[canonical] = current
            continue

        current.lines.append(line)

    return sections

def parse_pdf(path: str | Path) -> ParsedPDF:
    """Extract lines, boxes and sections from a PDF."""
    path = Path(path)
    lines: list[TextLine] = []
    page_sizes: list[tuple[float, float]] = []

    with pdfplumber.open(str(path)) as pdf:
        for page_no, page in enumerate(pdf.pages):
            page_sizes.append((float(page.width), float(page.height)))
            lines.extend(_lines_from_page(page, page_no, len(lines)))

    if not lines:
        raise ValueError(
            f"No text found in {path.name}. It is probably a scanned image — "
            "FolioProof needs a text-based PDF."
        )

    return ParsedPDF(
        path = str(path),
        page_count = len(page_sizes),
        page_sizes = page_sizes,
        lines = lines,
        sections = _segment_sections(lines),
    )