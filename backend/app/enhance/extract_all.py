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

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.config import settings
from app.enhance.llm import GroqLLM, LLMUnavailable, get_llm
from app.fusion.skills import canonical_skill
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

# The résumé gets the lion's share of the prompt budget; it is the only
# authoritative source for experience, education and projects. A dense one-page
# CV is ~3,200 characters, so this leaves generous headroom before the TPM
# ceiling forces a trade-off.
RESUME_CHAR_LIMIT = 12000

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

SYSTEM = """You extract a professional profile from someone's documents and
write the copy for their portfolio site. Do both in one pass.

Sources, in descending authority:
- RESUME: authoritative. Experience, education and projects come ONLY from here.
- LINKEDIN: use its About/Summary for voice. Do NOT add jobs or degrees from it.
- COVER LETTER: motivation and direction, for the About passage only.
- GITHUB: repo names and languages, for the skills list only. Do NOT turn repos
  into projects.

RULES
- Copy facts verbatim. Never invent employers, dates, metrics, scores, awards
  or technologies.
- experience[].organisation is the employer. Capture it even when the CV puts
  it on the line after the title.
- projects[].link: the exact URL as written in the résumé, or an empty string.
  Never substitute a GitHub repo you saw.
- projects[].description: 2 sentences, drawn only from what the résumé says.
- If something is absent, return an empty string or empty list.

ABOUT PASSAGE (first person, AT MOST 250 words, non-technical)
- Warm, like an introduction. "I build...", "I'm drawn to...".
- Aim 150-220 words. Name at most 2-3 technologies in the whole passage.
- Write about what the work does and who it helps, not the stack.
- If a LinkedIn Summary is present, keep its positioning and priorities.
- Lead with what they build, not with their degree.
- No bullets, headings, quotes, or sign-off.

hero_tagline: one sentence, under 25 words, plain language.

DISCREPANCIES
If the résumé and another source state DIFFERENT values for the same fact
(graduation year, job title at the same employer, a degree), record both in
`discrepancies`. Only genuine contradictions — never a fact simply absent from
one source. Empty list if none."""

# ---------------------------------------------------------------------------
# Source bundling
# ---------------------------------------------------------------------------

def build_source_bundle(
    resume_text: str = "",
    linkedin_text: str = "",
    cover_letter_text: str = "",
    github: dict[str, Any] | None = None,
    *,
    tight: bool = False,
    char_budget: int = 16000,
) -> str:
    """Concatenate every source into one clearly-delimited prompt payload.

    ``tight=True`` aggressively shrinks the supplementary sources so the model
    has more room in the shared TPM budget for its answer. Used on retry after
    a truncation. The résumé is kept generous either way — it is the only
    authoritative source for experience/education/projects.
    """
    parts: list[str] = []

    # Caps chosen to leave >=4.5k output tokens on Groq's 8k free-tier TPM
    # after the SYSTEM prompt and JSON schema. Tight mode aims for >=5.5k.
    resume_cap = 9000 if not tight else 7500
    linkedin_cap = 1600 if not tight else 700
    cover_cap = 1000 if not tight else 400
    github_repo_limit = 6 if not tight else 3
    github_desc_cap = 90 if not tight else 60

    if resume_text.strip():
        parts.append("===== RESUME =====\n" + resume_text.strip()[:resume_cap])

    if linkedin_text.strip():
        parts.append("===== LINKEDIN =====\n" + linkedin_text.strip()[:linkedin_cap])

    if cover_letter_text.strip():
        parts.append("===== COVER LETTER =====\n" + cover_letter_text.strip()[:cover_cap])

    if github:
        user = github.get("user") or {}
        lines = [f"profile: {user.get('login', '')} — {user.get('bio') or 'no bio'}"]
        for repo in (github.get("repos") or [])[:github_repo_limit]:
            langs = ", ".join(list((repo.get("_languages") or {}).keys())[:4]) or "—"
            desc = (repo.get("description") or "").strip()
            lines.append(f"- {repo['name']}: {desc[:github_desc_cap]} [langs: {langs}]")
        parts.append(
            "===== GITHUB (for skills only; not projects) =====\n" + "\n".join(lines)
        )

    return "\n\n".join(parts)[:char_budget]

def output_budget(system: str, user: str, schema: type[BaseModel]) -> int:
    """How many output tokens are left after the prompt, within the TPM limit.

    A fixed cap is the wrong shape here. Groq counts prompt + completion against
    one per-minute limit, so the ceiling moves with the résumé: too high and the
    request is rejected outright (413), too low and the answer is silently cut
    off mid-JSON. Deriving it means a long CV loses headroom gracefully instead
    of failing.

    A dense one-page CV needs ~3,300 completion tokens, so the floor is set well
    above that; if the prompt is so large that the floor cannot be met, the
    request is allowed to fail loudly rather than truncate quietly.
    """
    prompt_chars = len(system) + len(user) + len(
        json.dumps(schema.model_json_schema(), separators=(",", ":"))
    )
    prompt_tokens = prompt_chars // 4          # ~4 chars/token for English+JSON
    margin = 300                               # tokeniser estimate is not exact

    return max(1500, settings.groq_tpm_limit - prompt_tokens - margin)


def extract_portfolio(
    bundle: str,
    llm: GroqLLM | None = None,
    *,
    allow_truncated: bool = False,
) -> PortfolioContent:
    """The primary LLM call in the pipeline.

    Normally exactly one call per build. ``allow_truncated`` is used only as a
    last-resort fallback in the pipeline's retry ladder: it lets a truncated
    reply through if it still parses, so the user gets a mostly-complete
    portfolio instead of a hard failure on unusually dense résumés.
    """
    llm = llm or get_llm()
    if not llm.available:
        raise LLMUnavailable("no GROQ_API_KEY configured")

    user = "Extract the profile and write the copy from these sources:\n\n" + bundle
    return llm.complete_json(
        SYSTEM, user, PortfolioContent,
        temperature=0.25,
        # Derived, not fixed: prompt and completion share one per-minute limit,
        # and a cap that is too low truncates the JSON *silently*.
        max_tokens=output_budget(SYSTEM, user, PortfolioContent),
        allow_truncated=allow_truncated,
    )

# ---------------------------------------------------------------------------
# Structured content -> evidence-bound Claims
# ---------------------------------------------------------------------------

def _evidence(docs: dict[SourceId, ParsedPDF], value: str) -> Evidence | None:
    """Find which source document a value came from, and where on the page.

    Sources are tried in precedence order, so a fact present in both the résumé
    and LinkedIn anchors to the résumé. See ``_all_evidence`` when you also
    want the corroborating hits from lower-priority sources.
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

def _all_evidence(docs: dict[SourceId, ParsedPDF], value: str) -> list[Evidence]:
    """Every source that mentions ``value``, in precedence order.

    Powers multi-source corroboration: without this a fact present in résumé
    AND LinkedIn was only anchored to the résumé, so ``corroboration`` stayed
    at 1 and the "multi-source" metric was always zero.
    """
    out: list[Evidence] = []
    for source_id in ("resume", "linkedin", "cover_letter"):
        parsed = docs.get(source_id)  # type: ignore[arg-type]
        if parsed is None:
            continue
        line = parsed.find_line(value)
        if line is not None:
            out.append(Evidence(
                source_id=source_id,  # type: ignore[arg-type]
                locator=line.span(),
                raw_text=line.clean or line.text,
            ))
    return out

def _claim(
    docs: dict[SourceId, ParsedPDF],
    kind: ClaimKind,
    value: str,
    *,
    anchor: str | None = None,
    extra_anchors: list[str] | None = None,
    attributes: dict | None = None,
    fallback: Evidence | None = None,
    corroborate: Evidence | None = None,
) -> Claim | None:
    """Build a Claim, attaching evidence from every source that supports it.

    The primary evidence still comes from the highest-priority source (which
    keeps the "résumé wins" business rule). Additional matches from other
    sources are appended so ``corroboration`` reflects real multi-source
    support — a skill listed on both the résumé and LinkedIn will now report
    corroboration=2 instead of 1.

    ``corroborate`` attaches an out-of-PDF evidence item (typically a GitHub
    language) *in addition to* any PDF hits — different from ``fallback``,
    which is only used when no PDF evidence exists.
    """
    value = " ".join((value or "").split())
    if not value:
        return None

    lookup = anchor or value
    all_matches = _all_evidence(docs, lookup)
    primary = all_matches[0] if all_matches else fallback
    if primary is None:
        log.debug("dropping untraceable %s claim: %r", kind.value, value[:60])
        return None

    evidence: list[Evidence] = [primary]
    seen: set[tuple[str, str]] = {(primary.source_id, primary.raw_text)}

    # Corroborating hits from the other PDFs.
    for ev in all_matches[1:]:
        key = (ev.source_id, ev.raw_text)
        if key not in seen:
            evidence.append(ev)
            seen.add(key)

    # Out-of-PDF corroboration (e.g. GitHub language for a skill).
    if corroborate is not None:
        key = (corroborate.source_id, corroborate.raw_text)
        if key not in seen and corroborate.source_id not in {e.source_id for e in evidence}:
            evidence.append(corroborate)
            seen.add(key)

    for extra in extra_anchors or []:
        got = _evidence(docs, extra)
        if got is not None:
            key = (got.source_id, got.raw_text)
            if key not in seen:
                evidence.append(got)
                seen.add(key)

    return Claim(kind = kind, value = value, attributes = attributes or {}, evidence = evidence)

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
    # Skills are the most obvious multi-source claim: a language in the résumé
    # is almost always also in the GitHub language stats. Look up GitHub
    # evidence by BOTH the raw form and the canonical form so an LLM "JS"
    # still matches a GitHub "javascript".
    for skill in dict.fromkeys(content.skills):
        raw_key = skill.strip().lower()
        canon = canonical_skill(skill)
        gh_ev = github_skill_evidence.get(raw_key)
        if gh_ev is None and canon:
            gh_ev = github_skill_evidence.get(canon.lower())
        add(_claim(
            docs, ClaimKind.SKILL, skill,
            fallback = gh_ev,        # used only if no PDF hit
            corroborate = gh_ev,     # added *alongside* any PDF hit
        ))

    # -- experience --------------------------------------------------------
    for exp in content.experience:
        if not (exp.title or exp.organisation):
            continue
        label = " — ".join(p for p in (exp.title, exp.organisation) if p)
        add(_claim(
            docs, ClaimKind.ROLE, label,
            anchor = exp.title or exp.organisation,
            extra_anchors = [exp.organisation, *exp.bullets],
            attributes = {
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
            anchor = edu.institution or edu.degree,
            extra_anchors = [edu.degree, edu.score],
            attributes = {
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
            extra_anchors = [proj.description, *proj.technologies],
            attributes = {
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
            extra_anchors = [ach.description],
            attributes = {"organisation": ach.organisation, "description": ach.description},
        ))

    for cert in content.certifications:
        add(_claim(docs, ClaimKind.CERTIFICATION, cert))

    for pos in content.responsibilities:
        if not pos.position:
            continue
        add(_claim(
            docs, ClaimKind.ACHIEVEMENT, f"{pos.position} — {pos.organisation}".strip(" —"),
            anchor = pos.position,
            extra_anchors=[pos.description],
            attributes = {"organisation": pos.organisation, "description": pos.description},
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
        name = content.name or None,
        headline = content.job_title or None,
        email = content.contact.email or None,
        phone = content.contact.phone or None,
        location = content.contact.location or None,
        links = links,
    )

    return person, claims