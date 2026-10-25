"""Small text helpers shared by ingestion and rewriting."""
from __future__ import annotations

import re

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")

_MD_PATTERNS = [
    (re.compile(r"```.*?```", re.S), " "),          # fenced code
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), " "),     # images
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),  # links -> label
    (re.compile(r"<[^>]+>"), " "),                  # inline html / badges
    (re.compile(r"^\s{0,3}#{1,6}\s*", re.M), ""),   # headings
    (re.compile(r"[*_`>|]+"), ""),                  # emphasis, quotes, tables
    (re.compile(r"^\s*[-+*]\s+", re.M), ""),        # list bullets
]

def split_sentences(text: str) -> list[str]:
    """Split a passage into sentences."""
    text = " ".join((text or "").split())
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]

def strip_markdown(text: str) -> str:
    """Flatten README markdown into prose.

    Without it, a project card can show literal '# Project **bold**'.
    """
    out = text or ""
    for pattern, repl in _MD_PATTERNS:
        out = pattern.sub(repl, out)
    return " ".join(out.split())