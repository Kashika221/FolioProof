"""Skill fusion and cross-source conflict detection.

Deliberately *not* here any more: matching résumé projects onto GitHub
repositories. It was guesswork — `VeriFy: Authenticity Validator for Academia`
and `Academic_Validattor_SIH` are the same project but share almost no tokens,
while `VIO` matches half a dozen unrelated repos. A project now shows whatever
link the résumé itself gave (live demo or repo URL), and GitHub repositories
get their own Top Repositories section instead of being forced into pairs.

What remains is deterministic: canonicalise and merge skills across sources by
precedence, and report where two sources state different facts.
"""
from __future__ import annotations

import logging
import re

from app.fusion.priority import merge_by_priority, rank
from app.fusion.skills import canonical_skill
from app.models.claims import Claim, ClaimKind, Conflict, ConflictOption

log = logging.getLogger(__name__)

_YEAR_RE = re.compile(r"(19|20)\d{2}")

# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

def fuse_skills(claims: list[Claim]) -> list[Claim]:
    """Collapse skill claims onto canonical names, merging their evidence.

    "JS" from the résumé and "JavaScript" from GitHub become one claim backed
    by both, which is what makes the corroboration tick meaningful.
    """
    merged: dict[str, Claim] = {}
    for c in claims:
        canon = canonical_skill(c.value)
        if not canon:
            continue
        normalised = c.model_copy(update = {"value": canon})
        if canon in merged:
            merged[canon] = merge_by_priority([merged[canon], normalised])
        else:
            merged[canon] = normalised

    # Skills confirmed by more than one source sort first.
    return sorted(merged.values(), key = lambda c: (-c.corroboration, c.value.lower()))

# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def _auto_resolve(conflict: Conflict) -> Conflict:
    """Pick the winning option using source precedence.

    resume > linkedin > github > cover_letter. The user can still override the
    choice in the UI; this just means they never *have* to.
    """
    winner = min(conflict.options, key = lambda o: rank(o.evidence.source_id))
    conflict.resolved_value = winner.value
    return conflict

def detect_conflicts(claims: list[Claim]) -> list[Conflict]:
    """Find places where two sources disagree about the same underlying fact.

    Every conflict is returned already resolved by source precedence, so the
    generated portfolio is never blocked on user input.
    """
    conflicts: list[Conflict] = []

    # --- graduation / education years -------------------------------------
    year_by_source: dict[str, tuple[str, Claim]] = {}
    for c in (x for x in claims if x.kind is ClaimKind.EDUCATION):
        text = " ".join([
            c.value,
            str(c.attributes.get("end", "")),
            *(e.raw_text for e in c.evidence),
        ])
        years = _YEAR_RE.findall(text) and re.findall(r"(?:19|20)\d{2}", text)
        if years:
            latest = max(years)
            for ev in c.evidence:
                year_by_source.setdefault(ev.source_id, (latest, c))

    if len({v[0] for v in year_by_source.values()}) > 1:
        options = sorted(
            (
                ConflictOption(
                    value = f"{year} (from {src})",
                    evidence = next(
                        (e for e in claim.evidence if e.source_id == src),
                        claim.evidence[0],
                    ),
                )
                for src, (year, claim) in year_by_source.items()
            ),
            key = lambda o: rank(o.evidence.source_id),
        )
        conflicts.append(_auto_resolve(Conflict(
            field = "graduation_year",
            description = "Your sources give different graduation years.",
            options = options,
        )))

    # --- job titles for the same organisation -----------------------------
    by_org: dict[str, list[Claim]] = {}
    for c in (x for x in claims if x.kind is ClaimKind.ROLE):
        org = (c.attributes.get("organisation") or "").strip().lower()
        if org:
            by_org.setdefault(org, []).append(c)

    for org, group in by_org.items():
        titles: dict[str, tuple[str, object, str]] = {}
        for c in group:
            title = (c.attributes.get("title") or c.value).strip()
            for ev in c.evidence:
                titles.setdefault(title.lower(), (title, ev, ev.source_id))

        if len(titles) > 1 and len({v[2] for v in titles.values()}) > 1:
            options = sorted(
                (
                    ConflictOption(value=f"{title} (from {src})", evidence=ev)  # type: ignore[arg-type]
                    for _, (title, ev, src) in titles.items()
                ),
                key = lambda o: rank(o.evidence.source_id),
            )
            conflicts.append(_auto_resolve(Conflict(
                field = f"job_title:{org}",
                description = (
                    "Different job titles listed for "
                    f"{group[0].attributes.get('organisation')}."
                ),
                options = options,
            )))

    return conflicts