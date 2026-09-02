"""Single-call extraction.

Everything the portfolio needs — structured facts *and* the written copy —
comes back from ONE Groq call.

The previous design made 6-8 calls per build: one per PDF source, one per
project rewrite, one for the About paragraph. That was slow (~130 s), burned
the free tier's daily token budget in an afternoon, and gave the model a
fragmented view: the project rewriter saw one project's evidence and nothing
else, so it could not say "the thing they built at IIT Delhi feeds the thing
they built later".

Here the model sees the résumé, the LinkedIn export, the cover letter and the
GitHub profile together, and returns one validated `PortfolioContent`.

Provenance survives this change. Span attachment happens *after* extraction --
`content_to_claims()` looks each value back up in the parsed PDF and binds its
bounding box -- so it never mattered how many calls produced the values.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.enhance.llm import GroqLLM, LLMUnavailable, get_llm
from app.ingest.pdf_extract import ParsedPDF
from app.models.claims import (
    Claim,
    ClaimKind,
    Evidence,
    PersonInfo,
    SourceId,
)

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[\w\-./%?=&#+]+", re.I)


def normalise_url(raw: str | None) -> str | None:
    """Ensure a link is absolute.

    Résumés write bare hosts ("verify-v1.netlify.app") and the model copies them
    verbatim. A bare host in an href is a *relative path*, so the browser
    resolves it against the current origin and you end up at
    localhost:8000/api/preview/verify-v1.netlify.app.
    """
    url = (raw or "").strip().strip("<>()[],;")
    if not url:
        return None
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith(("mailto:", "tel:")):
        return url
    return "https://" + url.lstrip("/")


# ---------------------------------------------------------------------------
# What the model returns
# ---------------------------------------------------------------------------


class ContactInfo(BaseModel):
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""


class EducationItem(BaseModel):
    institution: str = ""
    degree: str = ""
    start: str = ""
    end: str = ""
    score: str = Field(default="", description="CGPA or percentage, verbatim")


class ExperienceItem(BaseModel):
    title: str = ""
    organisation: str = Field(default="", description="Employer name. Never leave blank if the CV shows one.")
    start: str = ""
    end: str = ""
    bullets: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class ProjectItem(BaseModel):
    name: str = ""
    description: str = Field(
        default="", description="2 sentences describing what it does, from the CV only"
    )
    technologies: list[str] = Field(default_factory=list)
    link: str = Field(
        default="",
        description="Live demo or repository URL as written in the CV. Empty if none.",
    )


class AchievementItem(BaseModel):
    title: str = ""
    organisation: str = ""
    description: str = ""


class ResponsibilityItem(BaseModel):
    position: str = ""
    organisation: str = ""
    description: str = ""


class Discrepancy(BaseModel):
    """A fact the sources disagree about.

    Detecting these used to fall out of having separate per-source claims. With
    one merged call the model is the only thing that sees both versions, so it
    reports them explicitly and the résumé's value still wins.
    """

    field: str = Field(default="", description="e.g. 'graduation year', 'job title at Acme'")
    resume_value: str = ""
    other_value: str = ""
    other_source: str = Field(default="linkedin", description="linkedin | github | cover_letter")


class PortfolioContent(BaseModel):
    """Everything the site needs, from one call."""

    name: str = ""
    job_title: str = Field(default="", description="Short role label, e.g. 'AI Engineer'")
    hero_tagline: str = Field(
        default="", description="One sentence for the hero, under 25 words"
    )
    about: str = Field(
        default="",
        description="First-person About passage, AT MOST 250 words, non-technical",
    )
    contact: ContactInfo = Field(default_factory=ContactInfo)
    skills: list[str] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    achievements: list[AchievementItem] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    responsibilities: list[ResponsibilityItem] = Field(default_factory=list)
    discrepancies: list[Discrepancy] = Field(
        default_factory=list,
        description='Facts where the résumé and another source disagree',
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM = """You extract a person's professional profile from their own documents
and write the copy for their portfolio website. You do both in one pass.

You are given up to four sources, in descending order of authority:

  RESUME     — the authoritative record. Experience, education and projects
               come from HERE AND ONLY HERE.
  LINKEDIN   — use its Summary/About text for voice. Do NOT add jobs or degrees
               from it; the résumé already has them, and LinkedIn restates them
               in a different shape which creates duplicates.
  COVER LETTER — motivation and direction, for the About passage only.
  GITHUB     — repository names and languages. Use only to enrich the skills
               list. Do NOT turn repositories into projects.

EXTRACTION RULES
- Copy facts verbatim. Never invent an employer, a date, a metric, a score,
  an award or a technology.
- experience[].organisation is the employer. A CV lists the title and dates on
  one line and the employer on the next — capture both. Never return a role
  with a blank organisation if the document shows one.
- projects[].link: the live demo or repo URL exactly as it appears in the
  résumé. If the résumé gives none, return an empty string — never guess a
  URL and never substitute a GitHub repository you saw.
- projects[].description: 2 sentences, drawn only from what the résumé says
  about that project.
- If something is absent, return an empty string or empty list.

WRITING THE ABOUT PASSAGE
- First person: "I build...", "I'm drawn to...". Warm, like someone
  introducing themselves.
- AT MOST 250 words. Aim for 150-220.
- NON-TECHNICAL. A recruiter or a family member should follow every sentence.
  Name at most two or three technologies in the whole passage. Write about
  what the work does and who it helps, not the stack.
- If a LinkedIn Summary is present, keep its positioning and priorities —
  polish it against the fuller profile rather than replacing it.
- Lead with what they build and why it interests them, not with their degree.
- No bullet points, no headings, no quotes, no sign-off.

hero_tagline: one sentence, under 25 words, plain language.

DISCREPANCIES
Compare the sources. If the résumé and LinkedIn (or any other source) state
DIFFERENT values for the same fact — a graduation year, a job title at the same
employer, a degree — record it in `discrepancies` with both values. Report only
genuine contradictions, never a fact that appears in one source and is simply
absent from the other. If there are none, return an empty list."""


# ---------------------------------------------------------------------------
# Source bundling
# ---------------------------------------------------------------------------


def build_source_bundle(
    resume_text: str = "",
    linkedin_text: str = "",
    cover_letter_text: str = "",
    github: dict[str, Any] | None = None,
    char_budget: int = 16000,
) -> str:
    """Concatenate every source into one clearly-delimited prompt payload."""
    parts: list[str] = []

    if resume_text.strip():
        parts.append("===== RESUME =====\n" + resume_text.strip()[:9000])

    if linkedin_text.strip():
        parts.append("===== LINKEDIN =====\n" + linkedin_text.strip()[:3500])

    if cover_letter_text.strip():
        parts.append("===== COVER LETTER =====\n" + cover_letter_text.strip()[:2500])

    if github:
        user = github.get("user") or {}
        lines = [f"profile: {user.get('login', '')} — {user.get('bio') or 'no bio'}"]
        for repo in (github.get("repos") or [])[:10]:
            langs = ", ".join((repo.get("_languages") or {}).keys()) or "—"
            desc = (repo.get("description") or "").strip()
            lines.append(f"- {repo['name']}: {desc[:110]} [languages: {langs}]")
        parts.append(
            "===== GITHUB (for skills only; not projects) =====\n" + "\n".join(lines)
        )

    return "\n\n".join(parts)[:char_budget]


def extract_portfolio(bundle: str, llm: GroqLLM | None = None) -> PortfolioContent:
    """The one and only LLM call in the pipeline.

    If Groq's quota is exhausted this raises `RateLimited` carrying the reset
    time. There is no fallback model and no silent degradation: a build that
    cannot be written should say so, not ship a page reading "Your Name".
    """
    llm = llm or get_llm()
    if not llm.available:
        raise LLMUnavailable("no GROQ_API_KEY configured")

    return llm.complete_json(
        SYSTEM,
        "Extract the profile and write the copy from these sources:\n\n" + bundle,
        PortfolioContent,
        temperature=0.25,
        # Real output for a dense CV is ~2k tokens. 6000 was pure headroom
        # and counted against the per-minute budget on every request.
        max_tokens=3500,
    )


# ---------------------------------------------------------------------------
# Structured content -> evidence-bound Claims
# ---------------------------------------------------------------------------


def _evidence(docs: dict[SourceId, ParsedPDF], value: str) -> Evidence | None:
    """Find which source document a value came from, and where on the page.

    Sources are tried in precedence order, so a fact present in both the résumé
    and LinkedIn anchors to the résumé.
    """
    for source_id in ("resume", "linkedin", "cover_letter"):
        parsed = docs.get(source_id)  # type: ignore[arg-type]
        if parsed is None:
            continue
        line = parsed.find_line(value)
        if line is not None:
            return Evidence(
                source_id=source_id,  # type: ignore[arg-type]
                locator=line.span(),
                raw_text=line.clean or line.text,
            )
    return None


def _claim(
    docs: dict[SourceId, ParsedPDF],
    kind: ClaimKind,
    value: str,
    *,
    anchor: str | None = None,
    extra_anchors: list[str] | None = None,
    attributes: dict | None = None,
    fallback: Evidence | None = None,
) -> Claim | None:
    value = " ".join((value or "").split())
    if not value:
        return None

    primary = _evidence(docs, anchor or value) or fallback
    if primary is None:
        log.debug("dropping untraceable %s claim: %r", kind.value, value[:60])
        return None

    evidence = [primary]
    seen = {primary.raw_text}
    for extra in extra_anchors or []:
        got = _evidence(docs, extra)
        if got is not None and got.raw_text not in seen:
            evidence.append(got)
            seen.add(got.raw_text)

    return Claim(kind=kind, value=value, attributes=attributes or {}, evidence=evidence)


def content_to_claims(
    content: PortfolioContent,
    docs: dict[SourceId, ParsedPDF],
    github_skill_evidence: dict[str, Evidence] | None = None,
) -> tuple[PersonInfo, list[Claim]]:
    """Bind the model's output back to the documents it came from."""
    claims: list[Claim] = []
    github_skill_evidence = github_skill_evidence or {}

    def add(c: Claim | None) -> None:
        if c is not None:
            claims.append(c)

    # -- skills ------------------------------------------------------------
    for skill in dict.fromkeys(content.skills):
        add(_claim(
            docs, ClaimKind.SKILL, skill,
            fallback=github_skill_evidence.get(skill.strip().lower()),
        ))

    # -- experience --------------------------------------------------------
    for exp in content.experience:
        if not (exp.title or exp.organisation):
            continue
        label = " — ".join(p for p in (exp.title, exp.organisation) if p)
        add(_claim(
            docs, ClaimKind.ROLE, label,
            anchor=exp.title or exp.organisation,
            extra_anchors=[exp.organisation, *exp.bullets],
            attributes={
                "title": exp.title,
                "organisation": exp.organisation,
                "start": exp.start,
                "end": exp.end,
                "bullets": exp.bullets,
                "technologies": exp.technologies,
            },
        ))

    # -- education ---------------------------------------------------------
    for edu in content.education:
        if not (edu.institution or edu.degree):
            continue
        label = " — ".join(p for p in (edu.institution, edu.degree) if p)
        add(_claim(
            docs, ClaimKind.EDUCATION, label,
            anchor=edu.institution or edu.degree,
            extra_anchors=[edu.degree, edu.score],
            attributes={
                "institution": edu.institution,
                "degree": edu.degree,
                "start": edu.start,
                "end": edu.end,
                "score": edu.score,
            },
        ))

    # -- projects ----------------------------------------------------------
    for proj in content.projects:
        if not proj.name:
            continue
        add(_claim(
            docs, ClaimKind.PROJECT, proj.name,
            extra_anchors=[proj.description, *proj.technologies],
            attributes={
                "description": proj.description,
                "technologies": proj.technologies,
                # Whatever link the résumé itself provided, made absolute.
                # GitHub repositories are never matched in here.
                "url": normalise_url(proj.link),
            },
        ))

    # -- achievements & certifications -------------------------------------
    for ach in content.achievements:
        if not ach.title:
            continue
        add(_claim(
            docs, ClaimKind.ACHIEVEMENT, ach.title,
            extra_anchors=[ach.description],
            attributes={"organisation": ach.organisation, "description": ach.description},
        ))

    for cert in content.certifications:
        add(_claim(docs, ClaimKind.CERTIFICATION, cert))

    for pos in content.responsibilities:
        if not pos.position:
            continue
        add(_claim(
            docs, ClaimKind.ACHIEVEMENT, f"{pos.position} — {pos.organisation}".strip(" —"),
            anchor=pos.position,
            extra_anchors=[pos.description],
            attributes={"organisation": pos.organisation, "description": pos.description},
        ))

    # -- person ------------------------------------------------------------
    links: dict[str, str] = {}
    for key in ("github", "linkedin", "website"):
        val = normalise_url(getattr(content.contact, key, ""))
        if val:
            links[key] = val

    # Backfill anything the model missed straight from the document text.
    resume = docs.get("resume")  # type: ignore[arg-type]
    if resume:
        for match in URL_RE.finditer(resume.full_text):
            url = match.group(0)
            low = url.lower()
            if "github.com" in low:
                links.setdefault("github", url)
            elif "linkedin.com" in low:
                links.setdefault("linkedin", url)

    person = PersonInfo(
        name=content.name or None,
        headline=content.job_title or None,
        email=content.contact.email or None,
        phone=content.contact.phone or None,
        location=content.contact.location or None,
        links=links,
    )

    return person, claims
