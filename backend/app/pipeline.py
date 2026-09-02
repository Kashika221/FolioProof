"""The end-to-end pipeline.

    parse sources -> ONE llm call -> bind spans -> fuse skills -> render

Exactly one LLM call is made per build, in `extract_portfolio`. Everything
after it is deterministic: span attachment, skill canonicalisation, conflict
detection and rendering all run without the model.

Experience, education and projects come from the résumé only. GitHub is used
for the skills union and for its own Top Repositories section; its repositories
are never matched onto résumé projects — a project shows whatever link the
résumé itself provided.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.enhance.extract_all import (
    PortfolioContent,
    build_source_bundle,
    content_to_claims,
    extract_portfolio,
)
from app.enhance.llm import GroqLLM, LLMUnavailable, get_llm
from app.enhance.text import split_sentences
from app.fusion.resolve import detect_conflicts, fuse_skills
from app.ingest.github import GitHubClient, GitHubError
from app.ingest.pdf_extract import ParsedPDF, parse_pdf
from app.models.claims import (
    Claim,
    ClaimKind,
    Conflict,
    ConflictOption,
    EnhancedBlock,
    Evidence,
    GeneratedSentence,
    GitHubField,
    PersonInfo,
    ProfileGraph,
    SourceDocument,
    SourceId,
)

log = logging.getLogger(__name__)


@dataclass
class BuildInputs:
    resume_path: str | Path | None = None
    linkedin_path: str | Path | None = None
    cover_letter_path: str | Path | None = None
    github_username: str | None = None
    max_repos: int = 10


@dataclass
class BuildResult:
    graph: ProfileGraph
    analytics: dict[str, Any] | None = None
    repositories: list[dict[str, Any]] = field(default_factory=list)
    gallery: list[dict[str, Any]] = field(default_factory=list)
    content: PortfolioContent | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _github_skill_evidence(payload: dict[str, Any]) -> dict[str, Evidence]:
    """Evidence for skills that only GitHub can attest to (repo languages).

    Without this a language present in the repos but absent from the résumé
    would be dropped, because no PDF line could be found to anchor it.
    """
    out: dict[str, Evidence] = {}
    login = (payload.get("user") or {}).get("login", "")
    for repo in payload.get("repos") or []:
        for lang in (repo.get("_languages") or {}):
            out.setdefault(lang.strip().lower(), Evidence(
                source_id="github",
                locator=GitHubField(repo=repo.get("full_name"), field="language",
                                    url=repo.get("html_url")),
                raw_text=f"{lang} used in {login}/{repo['name']}",
            ))
    return out


def build_profile(
    inputs: BuildInputs,
    llm: GroqLLM | None = None,
) -> BuildResult:
    started = time.perf_counter()
    llm = llm or get_llm()

    warnings: list[str] = []
    documents: list[SourceDocument] = []
    docs: dict[SourceId, ParsedPDF] = {}
    texts: dict[str, str] = {"resume": "", "linkedin": "", "cover_letter": ""}

    # -- 1. parse every PDF (no LLM) ---------------------------------------
    for path, source_id in (
        (inputs.resume_path, "resume"),
        (inputs.linkedin_path, "linkedin"),
        (inputs.cover_letter_path, "cover_letter"),
    ):
        if not path:
            continue
        try:
            parsed = parse_pdf(path)
        except Exception as exc:
            warnings.append(f"could not read {source_id}: {exc}")
            continue

        docs[source_id] = parsed          # type: ignore[index]
        texts[source_id] = parsed.full_text
        documents.append(SourceDocument(
            source_id=source_id,          # type: ignore[arg-type]
            filename=Path(path).name,
            stored_path=str(path),
            page_count=parsed.page_count,
            page_sizes=parsed.page_sizes,
        ))

    # -- 2. fetch GitHub (no LLM) ------------------------------------------
    analytics: dict[str, Any] | None = None
    repositories: list[dict[str, Any]] = []
    github_payload: dict[str, Any] | None = None
    if inputs.github_username:
        try:
            gh = GitHubClient()
            github_payload = gh.fetch_profile(
                inputs.github_username, max_repos=inputs.max_repos
            )
            analytics = gh.analytics(github_payload)
            repositories = gh.top_repositories(github_payload, limit=5)
        except GitHubError as exc:
            warnings.append(f"GitHub ingestion failed: {exc}")

    # -- 3. THE single LLM call --------------------------------------------
    bundle = build_source_bundle(
        resume_text=texts["resume"],
        linkedin_text=texts["linkedin"],
        cover_letter_text=texts["cover_letter"],
        github=github_payload,
    )

    content: PortfolioContent | None = None
    llm_calls = 0
    if bundle.strip() and llm.available:
        try:
            content = extract_portfolio(bundle, llm=llm)
            llm_calls = 1
        except LLMUnavailable as exc:
            warnings.append(f"LLM extraction unavailable: {exc}")
    elif not llm.available:
        warnings.append("GROQ_API_KEY not configured — no content could be generated")

    if content is None:
        content = PortfolioContent()

    # -- 4. bind values back to their source spans (no LLM) ----------------
    person, claims = content_to_claims(
        content, docs,
        github_skill_evidence=_github_skill_evidence(github_payload or {}),
    )

    if github_payload and not person.links.get("github"):
        person.links["github"] = (github_payload.get("user") or {}).get("html_url", "")

    # -- 5. deterministic fusion -------------------------------------------
    skills = fuse_skills([c for c in claims if c.kind is ClaimKind.SKILL])
    others = [c for c in claims if c.kind is not ClaimKind.SKILL]

    graph = ProfileGraph(
        person=person,
        claims=[*skills, *others],
        documents=documents,
    )

    # Conflicts come from two places: whatever can still be spotted structurally
    # in the claims, plus the discrepancies the model saw while reading all the
    # sources at once. The second path exists because merging the sources into
    # one call means LinkedIn's competing value never becomes its own claim.
    graph.conflicts = [
        *detect_conflicts(graph.claims),
        *_discrepancy_conflicts(content, docs),
    ]

    # -- 6. attach the generated copy (already written in step 3) ----------
    if content.about.strip():
        graph.blocks.append(_block_from_text(
            "bio", content.about, graph.claims, limit=250
        ))

    for claim in graph.by_kind(ClaimKind.PROJECT):
        desc = (claim.attributes.get("description") or "").strip()
        if desc:
            graph.blocks.append(_block_from_text(
                f"project:{claim.id}", desc, [claim]
            ))

    elapsed = time.perf_counter() - started

    return BuildResult(
        graph=graph,
        analytics=analytics,
        repositories=repositories,
        gallery=[],
        content=content,
        metrics={
            **graph.stats(),
            "llm_calls": llm_calls,
            "llm_available": llm.available,
            "top_repositories": len(repositories),
            "sources_used": sorted(docs) + (["github"] if github_payload else []),
            "about_words": len(content.about.split()),
            "hero_tagline": content.hero_tagline,
            "elapsed_seconds": round(elapsed, 2),
        },
        warnings=warnings,
    )


def _discrepancy_conflicts(
    content: PortfolioContent,
    docs: dict[SourceId, ParsedPDF],
) -> list[Conflict]:
    """Turn model-reported disagreements into resolved Conflict objects.

    The résumé's value always wins, matching the precedence order; the user can
    still override it in the UI.
    """
    from app.enhance.extract_all import _evidence as find_evidence

    out: list[Conflict] = []
    for d in content.discrepancies:
        if not (d.resume_value.strip() and d.other_value.strip()):
            continue
        if d.resume_value.strip().lower() == d.other_value.strip().lower():
            continue

        resume_ev = find_evidence(docs, d.resume_value)
        other_ev = find_evidence(docs, d.other_value)
        if resume_ev is None or other_ev is None:
            # Unanchored disagreements are the model's word alone; drop them.
            log.debug("dropping untraceable discrepancy: %s", d.field)
            continue

        options = [
            ConflictOption(value=f"{d.resume_value} (from resume)", evidence=resume_ev),
            ConflictOption(
                value=f"{d.other_value} (from {d.other_source})", evidence=other_ev
            ),
        ]
        out.append(Conflict(
            field=d.field or "unknown",
            description=(
                f"Your sources disagree about {d.field or 'a detail'}: the résumé "
                f"says “{d.resume_value}”, {d.other_source} says “{d.other_value}”."
            ),
            options=options,
            resolved_value=options[0].value,     # résumé wins by precedence
        ))
    return out


def _block_from_text(
    target: str,
    text: str,
    claims: list[Claim],
    limit: int | None = None,
) -> EnhancedBlock:
    """Wrap generated copy as sentences bound to the claims behind it."""
    if limit:
        words = text.split()
        if len(words) > limit:
            text = " ".join(words[:limit]).rstrip(",;: ") + "."

    evidence = [e for c in claims for e in c.evidence][:12]
    claim_ids = [c.id for c in claims]

    block = EnhancedBlock(target=target, original=text)
    block.sentences = [
        GeneratedSentence(text=s, claim_ids=claim_ids, evidence=evidence)
        for s in split_sentences(text)
    ]
    return block
