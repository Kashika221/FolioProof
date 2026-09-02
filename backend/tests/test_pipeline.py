"""Smoke tests. Run: .venv/Scripts/python.exe -m pytest -q

These cover the guarantees the project actually claims, not incidental details:
the evidence invariant, span-anchored provenance, entity resolution, skill
canonicalisation, and that all four themes render with colour overrides.
"""
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.enhance.extract_all import PortfolioContent, ProjectItem, content_to_claims
from app.enhance.text import split_sentences, strip_markdown
from app.fusion.priority import best_source, merge_by_priority, rank
from app.fusion.resolve import detect_conflicts, fuse_skills
from app.fusion.skills import canonical_skill, group_skills
from app.generate.portfolio import render_bundle, render_portfolio
from app.generate.themes import THEMES, SectionPalette, ThemeConfig
from app.ingest.pdf_extract import parse_pdf, _contains
from app.models.claims import Claim, ClaimKind, Evidence, GitHubField, PDFSpan
from app.pipeline import BuildInputs, build_profile

FIXTURE = Path(__file__).parent / "fixtures" / "sample_resume.pdf"


def _ev(source="resume", text="some source line"):
    loc = (PDFSpan(page=0, x0=1, top=1, x1=2, bottom=2) if source != "github"
           else GitHubField(field="description"))
    return Evidence(source_id=source, locator=loc, raw_text=text)


# --- the core invariant ----------------------------------------------------

def test_claim_requires_evidence():
    with pytest.raises(ValidationError):
        Claim(kind=ClaimKind.SKILL, value="Kubernetes", evidence=[])


def test_claim_with_evidence_is_valid():
    c = Claim(kind=ClaimKind.SKILL, value="FastAPI", evidence=[_ev()])
    assert c.corroboration == 1


def test_merging_claims_accumulates_sources():
    a = Claim(kind=ClaimKind.SKILL, value="Python", evidence=[_ev("resume")])
    b = Claim(kind=ClaimKind.SKILL, value="Python", evidence=[_ev("github", "Python repo")])
    assert a.merged_with(b).corroboration == 2


# --- extraction + provenance ----------------------------------------------

def test_pdf_sections_and_spans():
    parsed = parse_pdf(FIXTURE)
    assert {"skills", "projects", "education", "experience"} <= set(parsed.sections)
    span = parsed.find_span("Built a website.")
    assert span is not None and span.page == 0 and span.x1 > span.x0


def test_short_skill_does_not_match_inside_url():
    assert not _contains("github.com/aaravsharma", "git")
    assert _contains("tools: docker, git, postgresql", "git")




# --- fusion ----------------------------------------------------------------

def test_skill_canonicalisation():
    assert canonical_skill("JS") == "JavaScript"
    assert canonical_skill("k8s") == "Kubernetes"
    assert canonical_skill("Makefile") is None


def test_skill_fusion_merges_aliases():
    claims = [
        Claim(kind=ClaimKind.SKILL, value="JS", evidence=[_ev("resume")]),
        Claim(kind=ClaimKind.SKILL, value="JavaScript", evidence=[_ev("github")]),
    ]
    fused = fuse_skills(claims)
    assert len(fused) == 1
    assert fused[0].value == "JavaScript"
    assert fused[0].corroboration == 2






# --- source precedence -----------------------------------------------------

def test_priority_order_is_resume_linkedin_github():
    assert rank("resume") < rank("linkedin") < rank("github") < rank("cover_letter")
    assert best_source(["github", "resume", "linkedin"]) == "resume"
    assert best_source(["github", "cover_letter"]) == "github"


def test_higher_priority_source_wins_on_conflicting_value():
    resume = Claim(kind=ClaimKind.ROLE, value="Backend Engineer",
                   attributes={"title": "Backend Engineer"}, evidence=[_ev("resume")])
    github = Claim(kind=ClaimKind.ROLE, value="Software Dev",
                   attributes={"title": "Software Dev"}, evidence=[_ev("github")])

    # Order of arguments must not matter -- precedence decides, not position.
    for pair in ([resume, github], [github, resume]):
        merged = merge_by_priority(pair)
        assert merged.value == "Backend Engineer"
        assert merged.attributes["title"] == "Backend Engineer"
        assert merged.corroboration == 2


def test_github_keeps_fields_only_it_can_know():
    resume = Claim(kind=ClaimKind.PROJECT, value="VIO", evidence=[_ev("resume")],
                   attributes={"description": "hand-written summary"})
    github = Claim(kind=ClaimKind.PROJECT, value="vio", evidence=[_ev("github")],
                   attributes={"stars": 12, "url": "https://github.com/x/vio",
                               "description": "auto description"})
    merged = merge_by_priority([resume, github])
    assert merged.attributes["description"] == "hand-written summary"   # resume wins
    assert merged.attributes["stars"] == 12                             # github wins
    assert merged.attributes["url"].endswith("/vio")


def test_conflicts_are_auto_resolved_by_priority():

    resume = Claim(kind=ClaimKind.EDUCATION, value="B.Tech IT",
                   attributes={"end": "2026"},
                   evidence=[_ev("resume", "B.Tech Information Technology 2022 - 2026")])
    linkedin = Claim(kind=ClaimKind.EDUCATION, value="B.Tech IT",
                     attributes={"end": "2027"},
                     evidence=[_ev("linkedin", "B.Tech Information Technology 2022 - 2027")])

    conflicts = detect_conflicts([resume, linkedin])
    assert conflicts, "expected a graduation-year conflict"
    c = conflicts[0]
    assert c.is_resolved
    assert "resume" in c.resolved_value
    assert c.options[0].evidence.source_id == "resume"   # most authoritative first


# --- single-call extraction ------------------------------------------------

def test_pipeline_makes_exactly_one_llm_call(monkeypatch):
    """The whole build must cost one call, not one per section."""
    import app.enhance.extract_all as ea

    calls = {"n": 0}

    def fake_extract(bundle, llm=None):
        calls["n"] += 1
        return PortfolioContent(
            name="Test Person",
            about="I build things.",
            skills=["Python", "FastAPI"],
            projects=[ProjectItem(name="Built a website.", description="A web app.",
                                  link="https://example.com")],
        )

    monkeypatch.setattr("app.pipeline.extract_portfolio", fake_extract)
    monkeypatch.setattr("app.pipeline.get_llm", lambda: _AlwaysAvailableLLM())

    result = build_profile(BuildInputs(resume_path=FIXTURE))
    assert calls["n"] == 1
    assert result.metrics["llm_calls"] == 1


class _AlwaysAvailableLLM:
    available = True


def test_project_link_comes_from_resume_not_github():
    """Projects show the link the résumé gave; repos are never matched in."""
    parsed = parse_pdf(FIXTURE)
    content = PortfolioContent(projects=[
        ProjectItem(name="Built a website.", description="A small site.",
                    link="https://my-demo.vercel.app"),
    ])
    _, claims = content_to_claims(content, {"resume": parsed})
    projects = [c for c in claims if c.kind is ClaimKind.PROJECT]
    assert projects
    assert projects[0].attributes["url"] == "https://my-demo.vercel.app"


def test_project_without_a_resume_link_gets_none():
    parsed = parse_pdf(FIXTURE)
    content = PortfolioContent(projects=[ProjectItem(name="Built a website.")])
    _, claims = content_to_claims(content, {"resume": parsed})
    projects = [c for c in claims if c.kind is ClaimKind.PROJECT]
    assert projects[0].attributes["url"] is None


def test_extracted_values_are_still_span_anchored():
    """One call instead of eight must not cost us provenance."""
    parsed = parse_pdf(FIXTURE)
    content = PortfolioContent(
        skills=["FastAPI", "Docker"],
        projects=[ProjectItem(name="Built a website.")],
    )
    _, claims = content_to_claims(content, {"resume": parsed})
    assert claims
    for c in claims:
        assert c.evidence
        assert c.evidence[0].locator.kind == "pdf"
        assert c.evidence[0].locator.x1 > c.evidence[0].locator.x0


def test_untraceable_values_are_dropped_not_invented():
    parsed = parse_pdf(FIXTURE)
    content = PortfolioContent(skills=["Quantum Blockchain Synergy"])
    _, claims = content_to_claims(content, {"resume": parsed})
    assert not claims


# --- rendering -------------------------------------------------------------

def test_all_four_themes_render():
    result = build_profile(BuildInputs(resume_path=FIXTURE))
    assert len(THEMES) == 4
    for key in THEMES:
        html = render_portfolio(result.graph, ThemeConfig(theme=key))
        assert "<!doctype html>" in html.lower()
        assert 'data-section="projects"' in html


def test_per_section_colour_override_reaches_css():
    result = build_profile(BuildInputs(resume_path=FIXTURE))
    cfg = ThemeConfig(
        theme="minimal",
        overrides={"projects": SectionPalette(bg="#101014", fg="#f0f0f0", accent="#ff5c8a")},
    )
    html = render_portfolio(result.graph, cfg)
    assert "#ff5c8a" in html
    assert "#101014" in html
    # The selector must survive templating intact. Jinja autoescape once turned
    # [data-section="projects"] into [data-section=&#34;projects&#34;], which is
    # valid HTML and completely dead CSS -- every section silently lost its palette.
    assert '[data-section="projects"] {' in html
    assert "&#34;" not in html.split("</style>")[0]


def test_bundle_splits_into_separate_assets():
    """Export must be a real static site, not one inlined blob."""
    result = build_profile(BuildInputs(resume_path=FIXTURE))
    gallery = [{"id": "abc", "filename": "shot.png", "caption": "Demo day",
                "url": "/api/profile/x/gallery/shot.png"}]
    files = render_bundle(result.graph, ThemeConfig(theme="playful"), gallery=gallery)

    assert set(files) == {"index.html", "style.css", "script.js"}

    html, css, js = files["index.html"], files["style.css"], files["script.js"]
    assert '<link rel="stylesheet" href="style.css">' in html
    assert '<script src="script.js" defer></script>' in html
    assert "<style>" not in html                    # nothing inlined
    assert "setProvenanceMode" not in html          # JS lives in script.js
    assert "setProvenanceMode" in js
    assert '[data-section="projects"] {' in css

    # Gallery paths must be rewritten to the zip layout, not left as API URLs.
    assert 'src="images/shot.png"' in html
    assert "/api/profile/" not in html




def test_legacy_glass_key_maps_to_playful():
    """Profiles saved before the rename must still load."""
    assert ThemeConfig(theme="glass").theme == "playful"
    assert "playful" in THEMES and "glass" not in THEMES


def test_bare_project_links_are_made_absolute():
    """A bare host in an href is a relative path -- it resolved against
    localhost and sent visitors to /api/preview/verify-v1.netlify.app."""
    from app.enhance.extract_all import normalise_url

    assert normalise_url("verify-v1.netlify.app") == "https://verify-v1.netlify.app"
    assert normalise_url("https://x.dev/") == "https://x.dev/"
    assert normalise_url("//cdn.example.com") == "https://cdn.example.com"
    assert normalise_url("  ") is None
    assert normalise_url(None) is None


def test_project_link_label_and_no_gallery_caption():
    from app.models.claims import ProfileGraph

    parsed = parse_pdf(FIXTURE)
    content = PortfolioContent(projects=[
        ProjectItem(name="Built a website.", description="A small site.",
                    link="verify-v1.netlify.app"),      # deliberately bare
    ])
    person, claims = content_to_claims(content, {"resume": parsed})
    graph = ProfileGraph(person=person, claims=claims)

    gallery = [{"id": "a", "filename": "shot.png", "caption": "Secret internal name",
                "url": "/x/shot.png"}]
    html = render_portfolio(graph, ThemeConfig(theme="playful"), gallery=gallery)

    assert "Project Link" in html
    assert ">Source<" not in html
    # Bare host must have been made absolute, or the browser treats it as a
    # path relative to the current origin.
    assert 'href="https://verify-v1.netlify.app"' in html

    # The caption survives as alt text for screen readers but must not render.
    assert "<figcaption>" not in html
    assert ">Secret internal name<" not in html


def test_invalid_theme_and_colour_rejected():
    with pytest.raises(ValidationError):
        ThemeConfig(theme="cyberpunk")
    with pytest.raises(ValidationError):
        SectionPalette(bg="not-a-colour", fg="#fff", accent="#000")


# --- helpers ---------------------------------------------------------------



def test_sentence_splitting():
    assert len(split_sentences("One. Two! Three?")) == 3


def test_model_reported_discrepancy_resolves_to_the_resume():
    """A disagreement the model spots must resolve to the résumé's value."""
    from app.enhance.extract_all import Discrepancy
    from app.pipeline import _discrepancy_conflicts

    parsed = parse_pdf(FIXTURE)
    content = PortfolioContent(discrepancies=[Discrepancy(
        field="graduation year",
        resume_value="2022 - 2026",          # present in the fixture
        other_value="Built a website.",      # also a real line, so both anchor
        other_source="linkedin",
    )])

    conflicts = _discrepancy_conflicts(content, {"resume": parsed})
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.is_resolved
    assert "from resume" in c.resolved_value
    assert c.options[0].evidence.source_id == "resume"


def test_untraceable_discrepancies_are_dropped():
    """The model's word alone is not enough — both sides must anchor."""
    from app.enhance.extract_all import Discrepancy
    from app.pipeline import _discrepancy_conflicts

    parsed = parse_pdf(FIXTURE)
    content = PortfolioContent(discrepancies=[Discrepancy(
        field="graduation year",
        resume_value="totally absent value",
        other_value="also absent",
        other_source="linkedin",
    )])
    assert _discrepancy_conflicts(content, {"resume": parsed}) == []


def test_pipeline_produces_traceable_profile():
    result = build_profile(BuildInputs(resume_path=FIXTURE))

    # This one exercises the real Groq call. The free tier has a daily token
    # budget, so skip rather than fail when it is exhausted — a quota is not a
    # regression, and every other guarantee is covered by offline tests.
    if not result.graph.claims and result.warnings:
        pytest.skip(f"LLM unavailable: {result.warnings[0][:120]}")

    assert result.graph.claims
    assert result.metrics["claims"] > 10
    for claim in result.graph.claims:
        assert claim.evidence, f"{claim.value} lost its evidence"
