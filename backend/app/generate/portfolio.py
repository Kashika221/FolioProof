"""Render a ProfileGraph into a standalone portfolio page.

Every sentence that came out of the LLM is wrapped in a span carrying
`data-provenance` (the evidence behind it) and `data-source` (the most
authoritative source backing it). That is what powers the provenance viewer:
the page itself knows where each of its own sentences came from, so nothing has
to be reconstructed client-side.
"""
from __future__ import annotations

import html
import json
from typing import Any

from jinja2 import Environment, select_autoescape

from app.fusion.skills import group_skills
from app.generate.themes import ThemeConfig, build_css
from app.models.claims import ClaimKind, EnhancedBlock, ProfileGraph

LANG_COLOURS = ["#3572A5", "#f1e05a", "#e34c26", "#563d7c", "#b07219",
                "#00ADD8", "#dea584", "#4F5D95"]

env = Environment(autoescape = select_autoescape(["html"]))

def _provenance_payload(block: EnhancedBlock) -> list[dict[str, Any]]:
    out = []
    for s in block.sentences:
        out.append({
            "text": s.text,
            "source": s.primary_source,
            "note": s.note,
            "claim_ids": s.claim_ids,
            "evidence": [
                {
                    "source": e.source_id,
                    "text": e.short(240),
                    "locator": e.locator.model_dump(),
                }
                for e in s.evidence[:6]
            ],
        })
    return out

def render_block(block: EnhancedBlock | None) -> str:
    """Render published sentences as provenance-tagged spans."""
    if block is None:
        return ""
    parts = []
    for s in block.sentences:
        payload = html.escape(json.dumps({
            "note": s.note,
            "evidence": [
                {"source": e.source_id, "text": e.short(220), "locator": e.locator.model_dump()}
                for e in s.evidence[:4]
            ],
        }), quote = True)
        parts.append(
            f'<span data-provenance="{payload}" data-source="{s.primary_source or ""}">'
            f"{html.escape(s.text)}</span>"
        )
    return " ".join(parts)

PORTFOLIO_JS = r"""// Mobile nav toggle + active-section highlighting.
(function () {
  var toggle = document.querySelector('.topnav-toggle');
  var links = document.getElementById('navlinks');
  if (toggle && links) {
    toggle.addEventListener('click', function () {
      var open = links.classList.toggle('open');
      toggle.setAttribute('aria-expanded', String(open));
    });
    links.addEventListener('click', function (e) {
      if (e.target.tagName === 'A') {
        links.classList.remove('open');
        toggle.setAttribute('aria-expanded', 'false');
      }
    });
  }

  var anchors = [].slice.call(document.querySelectorAll('.topnav-links a'));
  if (!anchors.length || !('IntersectionObserver' in window)) return;
  var byId = {};
  anchors.forEach(function (a) { byId[a.getAttribute('href').slice(1)] = a; });

  var obs = new IntersectionObserver(function (entries) {
    entries.forEach(function (en) {
      var a = byId[en.target.id];
      if (a) a.style.opacity = en.isIntersecting ? '1' : '0.75';
    });
  }, { rootMargin: '-45% 0px -50% 0px' });

  Object.keys(byId).forEach(function (id) {
    var el = document.getElementById(id);
    if (el) obs.observe(el);
  });
})();

// Provenance mode: adds highlighting + a hover panel showing the source text.
(function () {
  var panel = document.createElement('div');
  panel.style.cssText = 'position:fixed;bottom:16px;left:16px;right:16px;max-width:640px;' +
    'margin:auto;padding:14px 16px;border-radius:10px;background:#111;color:#eee;' +
    'font:13px/1.5 ui-sans-serif,system-ui,sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.35);' +
    'display:none;z-index:9999;';
  document.body.appendChild(panel);

  document.addEventListener('mouseover', function (e) {
    var el = e.target.closest('[data-provenance]');
    if (!el || !document.body.classList.contains('provenance-on')) return;
    var data;
    try { data = JSON.parse(el.getAttribute('data-provenance')); } catch (_) { return; }
    var rows = (data.evidence || []).map(function (ev) {
      return '<div style="margin-top:6px"><b style="color:#7aa2ff">' + ev.source +
             '</b> — ' + ev.text.replace(/</g, '&lt;') + '</div>';
    }).join('');
    panel.innerHTML = '<b>Source evidence</b>' + (rows || '<div>(none)</div>') +
      (data.note ? '<div style="margin-top:8px;color:#f8b4b4">' + data.note + '</div>' : '');
    panel.style.display = 'block';
  });
  document.addEventListener('mouseout', function (e) {
    if (e.target.closest('[data-provenance]')) panel.style.display = 'none';
  });

  window.setProvenanceMode = function (on) {
    document.body.classList.toggle('provenance-on', !!on);
    if (!on) panel.style.display = 'none';
  };
  window.addEventListener('message', function (e) {
    if (e.data && e.data.type === 'folioproof:provenance') window.setProvenanceMode(e.data.on);
  });
})();
"""

TEMPLATE = env.from_string("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ person.name or 'Portfolio' }}</title>
<meta name="description" content="{{ meta_description }}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Poppins:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&display=swap" rel="stylesheet">
{% if external_assets %}
<link rel="stylesheet" href="style.css">
{% else %}
<style>{{ css|safe }}</style>
{% endif %}
</head>
<body>

{% if nav %}
<nav class="topnav" aria-label="Sections">
  <div class="topnav-inner">
    <a class="topnav-brand" href="#home">{{ person.name or 'Portfolio' }}</a>
    <button class="topnav-toggle" aria-expanded="false" aria-controls="navlinks"
            aria-label="Toggle navigation">☰</button>
    <div class="topnav-links" id="navlinks">
      {% for n in nav %}<a href="#{{ n.id }}">{{ n.label }}</a>{% endfor %}
    </div>
  </div>
</nav>
{% endif %}

<section class="section hero" data-section="hero" id="home">
  <div class="section-inner">
    <h1>{{ person.name or 'Your Name' }}</h1>
    <p class="headline">{{ person.headline or tagline }}</p>
    <div class="links">
      {% if person.email %}<a class="btn" href="mailto:{{ person.email }}">Email me</a>{% endif %}
      {% for label, url in person.links.items() %}
        <a class="btn ghost" href="{{ url }}" target="_blank" rel="noopener">{{ label|capitalize }}</a>
      {% endfor %}
      {% if resume_url %}<a class="btn ghost" href="{{ resume_url }}" download>Download résumé</a>{% endif %}
    </div>
  </div>
</section>

{% if bio_html %}
<section class="section" data-section="about" id="about">
  <div class="section-inner">
    <h2 class="section-title">About</h2>
    <p>{{ bio_html|safe }}</p>
  </div>
</section>
{% endif %}

{% if skill_groups %}
<section class="section" data-section="skills" id="skills">
  <div class="section-inner">
    <h2 class="section-title">Skills</h2>
    <div class="grid three">
      {% for category, items in skill_groups.items() %}
      <div class="card">
        <h3>{{ category }}</h3>
        <div>
          {% for s in items %}
          <span class="chip" data-corroborated="{{ 'true' if s.corroborated else 'false' }}"
                title="{{ s.sources|join(', ') }}">{{ s.name }}</span>
          {% endfor %}
        </div>
      </div>
      {% endfor %}
    </div>
    <p class="footer-note">✓ marks a skill confirmed by more than one source.</p>
  </div>
</section>
{% endif %}

{% if projects %}
<section class="section" data-section="projects" id="projects">
  <div class="section-inner">
    <h2 class="section-title">Projects</h2>
    <div class="grid two">
      {% for p in projects %}
      <article class="card" data-index="{{ '%02d'|format(loop.index) }}">
        <h3>{{ p.name }}</h3>
        <p>{{ p.description|safe }}</p>
        <div>{% for t in p.tech %}<span class="chip">{{ t }}</span>{% endfor %}</div>
        <p style="margin-top:12px">
          {% if p.url %}<a href="{{ p.url }}" target="_blank" rel="noopener">Project Link</a>{% endif %}
          {% if p.url and p.demo %} · {% endif %}
          {% if p.demo %}<a href="{{ p.demo }}" target="_blank" rel="noopener">Live demo</a>{% endif %}
          {% if p.stars %} · ★ {{ p.stars }}{% endif %}
        </p>
      </article>
      {% endfor %}
    </div>
  </div>
</section>
{% endif %}

{% if repositories %}
<section class="section" data-section="repositories" id="repositories">
  <div class="section-inner">
    <h2 class="section-title">Top Repositories</h2>
    <div class="grid two">
      {% for r in repositories %}
      <article class="card repo" data-index="{{ '%02d'|format(loop.index) }}">
        <div class="repo-head">
          <h3><a href="{{ r.url }}" target="_blank" rel="noopener">{{ r.name }}</a></h3>
          <span class="repo-meta">
            {% if r.stars %}★ {{ r.stars }}{% endif %}
            {% if r.forks %} ⑂ {{ r.forks }}{% endif %}
          </span>
        </div>
        {% if r.description %}<p>{{ r.description }}</p>{% endif %}
        {% if r.languages %}
        <div class="repo-langs">
          {% for l in r.languages %}<span class="chip">{{ l.name }} {{ l.percent }}%</span>{% endfor %}
        </div>
        {% endif %}
        <div>{% for tpc in r.topics %}<span class="chip">{{ tpc }}</span>{% endfor %}</div>
        <p style="margin-top:12px">
          <a href="{{ r.url }}" target="_blank" rel="noopener">Repository</a>
          {% if r.homepage %} · <a href="{{ r.homepage }}" target="_blank" rel="noopener">Live</a>{% endif %}
          {% if r.updated %} · updated {{ r.updated }}{% endif %}
        </p>
      </article>
      {% endfor %}
    </div>
  </div>
</section>
{% endif %}

{% if timeline %}
<section class="section" data-section="experience" id="experience">
  <div class="section-inner">
    <h2 class="section-title">Experience</h2>
    <div class="timeline">
      {% for item in timeline %}
      <div class="item">
        <h3 style="margin:0 0 2px">{{ item.title }}</h3>
        {% if item.org %}<div class="org">{{ item.org }}</div>{% endif %}
        {% if item.when %}<div class="when">{{ item.when }}</div>{% endif %}
        {% if item.bullets %}
        <ul>{% for b in item.bullets %}<li>{{ b }}</li>{% endfor %}</ul>
        {% endif %}
      </div>
      {% endfor %}
    </div>
  </div>
</section>
{% endif %}

{% if education %}
<section class="section" data-section="education" id="education">
  <div class="section-inner">
    <h2 class="section-title">Education</h2>
    <div class="timeline">
      {% for e in education %}
      <div class="item">
        <h3 style="margin:0 0 2px">{{ e.title }}</h3>
        {% if e.degree %}<div class="org">{{ e.degree }}</div>{% endif %}
        <div class="when">
          {{ e.when }}{% if e.when and e.score %} · {% endif %}{{ e.score }}
        </div>
      </div>
      {% endfor %}
    </div>
  </div>
</section>
{% endif %}

{% if gallery %}
<section class="section" data-section="gallery" id="gallery">
  <div class="section-inner">
    <h2 class="section-title">Gallery</h2>
    <div class="gallery">
      {% for g in gallery %}
      <figure class="shot">
        {# The caption is metadata for the editor, not something visitors need. #}
        <img src="{{ g.url }}" alt="{{ g.caption }}" loading="lazy">
      </figure>
      {% endfor %}
    </div>
  </div>
</section>
{% endif %}

{% if analytics %}
<section class="section" data-section="github" id="github">
  <div class="section-inner">
    <h2 class="section-title">GitHub</h2>
    <div class="stats">
      <div class="stat"><div class="n">{{ analytics.public_repos }}</div><div class="k">Repositories</div></div>
      <div class="stat"><div class="n">{{ analytics.total_stars }}</div><div class="k">Stars</div></div>
      <div class="stat"><div class="n">{{ analytics.total_forks }}</div><div class="k">Forks</div></div>
      <div class="stat"><div class="n">{{ analytics.followers }}</div><div class="k">Followers</div></div>
    </div>
    {% if analytics.languages %}
    <div class="langbar">
      {% for l in analytics.languages %}
      <span style="width:{{ l.percent }}%;background:{{ l.colour }}" title="{{ l.name }} {{ l.percent }}%"></span>
      {% endfor %}
    </div>
    <div class="langkey">
      {% for l in analytics.languages %}
      <span><i style="background:{{ l.colour }}"></i>{{ l.name }} {{ l.percent }}%</span>
      {% endfor %}
    </div>
    {% endif %}
  </div>
</section>
{% endif %}

{% if achievements %}
<section class="section" data-section="achievements" id="achievements">
  <div class="section-inner">
    <h2 class="section-title">Achievements &amp; Certifications</h2>
    <div class="grid three">
      {% for a in achievements %}
      <div class="card"><p style="margin:0;color:var(--fg)">{{ a }}</p></div>
      {% endfor %}
    </div>
  </div>
</section>
{% endif %}

<section class="section" data-section="contact" id="contact">
  <div class="section-inner">
    <h2 class="section-title">Contact</h2>
    <p>
      {% if person.email %}<a href="mailto:{{ person.email }}">{{ person.email }}</a>{% endif %}
      {% if person.location %} · {{ person.location }}{% endif %}
    </p>
    <p class="footer-note">
      Generated by FolioProof from {{ source_count }} source(s).
      Every sentence on this page is traceable to the document it came from.
    </p>
  </div>
</section>

{% if external_assets %}
<script src="script.js" defer></script>
{% else %}
<script>
// Mobile nav toggle + active-section highlighting.
(function () {
  var toggle = document.querySelector('.topnav-toggle');
  var links = document.getElementById('navlinks');
  if (toggle && links) {
    toggle.addEventListener('click', function () {
      var open = links.classList.toggle('open');
      toggle.setAttribute('aria-expanded', String(open));
    });
    links.addEventListener('click', function (e) {
      if (e.target.tagName === 'A') {
        links.classList.remove('open');
        toggle.setAttribute('aria-expanded', 'false');
      }
    });
  }

  var anchors = [].slice.call(document.querySelectorAll('.topnav-links a'));
  if (!anchors.length || !('IntersectionObserver' in window)) return;
  var byId = {};
  anchors.forEach(function (a) { byId[a.getAttribute('href').slice(1)] = a; });

  var obs = new IntersectionObserver(function (entries) {
    entries.forEach(function (en) {
      var a = byId[en.target.id];
      if (a) a.style.opacity = en.isIntersecting ? '1' : '0.75';
    });
  }, { rootMargin: '-45% 0px -50% 0px' });

  Object.keys(byId).forEach(function (id) {
    var el = document.getElementById(id);
    if (el) obs.observe(el);
  });
})();

// Provenance mode: adds highlighting + a hover panel showing the source text.
(function () {
  var panel = document.createElement('div');
  panel.style.cssText = 'position:fixed;bottom:16px;left:16px;right:16px;max-width:640px;' +
    'margin:auto;padding:14px 16px;border-radius:10px;background:#111;color:#eee;' +
    'font:13px/1.5 ui-sans-serif,system-ui,sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.35);' +
    'display:none;z-index:9999;';
  document.body.appendChild(panel);

  document.addEventListener('mouseover', function (e) {
    var el = e.target.closest('[data-provenance]');
    if (!el || !document.body.classList.contains('provenance-on')) return;
    var data;
    try { data = JSON.parse(el.getAttribute('data-provenance')); } catch (_) { return; }
    var rows = (data.evidence || []).map(function (ev) {
      return '<div style="margin-top:6px"><b style="color:#7aa2ff">' + ev.source +
             '</b> — ' + ev.text.replace(/</g, '&lt;') + '</div>';
    }).join('');
    panel.innerHTML = '<b>Source evidence</b>' + (rows || '<div>(none)</div>') +
      (data.note ? '<div style="margin-top:8px;color:#f8b4b4">' + data.note + '</div>' : '');
    panel.style.display = 'block';
  });
  document.addEventListener('mouseout', function (e) {
    if (e.target.closest('[data-provenance]')) panel.style.display = 'none';
  });

  window.setProvenanceMode = function (on) {
    document.body.classList.toggle('provenance-on', !!on);
    if (!on) panel.style.display = 'none';
  };
  window.addEventListener('message', function (e) {
    if (e.data && e.data.type === 'folioproof:provenance') window.setProvenanceMode(e.data.on);
  });
})();
</script>
{% endif %}
</body>
</html>
""")

def _block_for(graph: ProfileGraph, target: str) -> EnhancedBlock | None:
    return next((b for b in graph.blocks if b.target == target), None)

def build_view_model(graph: ProfileGraph, analytics: dict | None = None,
                     resume_url: str | None = None,
                     repositories: list[dict] | None = None,
                     gallery: list[dict] | None = None) -> dict[str, Any]:
    """Flatten the ProfileGraph into what the template needs."""
    skills = graph.by_kind(ClaimKind.SKILL)
    grouped_names = group_skills([c.value for c in skills])
    by_name = {c.value: c for c in skills}

    skill_groups = {
        cat: [
            {
                "name": n,
                "corroborated": by_name[n].corroboration > 1 if n in by_name else False,
                "sources": sorted(by_name[n].sources) if n in by_name else [],
            }
            for n in names
        ]
        for cat, names in grouped_names.items()
    }

    projects = []
    for c in graph.by_kind(ClaimKind.PROJECT):
        block = _block_for(graph, f"project:{c.id}")
        description = render_block(block) or html.escape(
            c.attributes.get("description") or ""
        )
        tech = list(dict.fromkeys(
            [*(c.attributes.get("technologies") or []),
             *(c.attributes.get("topics") or []),
             *(c.attributes.get("languages") or [])]
        ))[:6]
        projects.append({
            "name": c.value,
            "description": description,
            "tech": tech,
            "url": c.attributes.get("url"),
            "demo": c.attributes.get("homepage"),
            "stars": c.attributes.get("stars") or 0,
        })

    timeline = []
    for c in graph.by_kind(ClaimKind.ROLE):
        start = (c.attributes.get("start") or "").strip()
        end = (c.attributes.get("end") or "").strip()
        title = (c.attributes.get("title") or c.value).strip()
        org = (c.attributes.get("organisation") or "").strip()

        # `when` must never restate the title. The old fallback did exactly
        # that when dates were missing, so every entry printed twice.
        when = " – ".join(x for x in (start, end) if x)
        if when and when.lower() in title.lower():
            when = ""

        timeline.append({
            "title": title,
            "org": org,
            "when": when,
            "bullets": (c.attributes.get("bullets") or [])[:4],
        })

    education = []
    for c in graph.by_kind(ClaimKind.EDUCATION):
        start = (c.attributes.get("start") or "").strip()
        end = (c.attributes.get("end") or "").strip()
        education.append({
            "title": (c.attributes.get("institution") or c.value).strip(),
            "degree": (c.attributes.get("degree") or "").strip(),
            "score": (c.attributes.get("score") or "").strip(),
            "when": " – ".join(x for x in (start, end) if x),
        })

    achievements = [c.value for c in graph.by_kind(ClaimKind.ACHIEVEMENT)]
    achievements += [c.value for c in graph.by_kind(ClaimKind.CERTIFICATION)]

    if analytics and analytics.get("languages"):
        for i, l in enumerate(analytics["languages"]):
            l["colour"] = LANG_COLOURS[i % len(LANG_COLOURS)]

    bio_block = _block_for(graph, "bio")
    top_skills = ", ".join(n for names in grouped_names.values() for n in names[:2])

    # Only advertise sections that actually rendered — a nav link to an empty
    # anchor is worse than no link.
    nav = [
        {"id": "about", "label": "About", "on": bool(bio_block)},
        {"id": "skills", "label": "Skills", "on": bool(skill_groups)},
        {"id": "projects", "label": "Projects", "on": bool(projects)},
        {"id": "repositories", "label": "Repositories", "on": bool(repositories)},
        {"id": "experience", "label": "Experience", "on": bool(timeline)},
        {"id": "education", "label": "Education", "on": bool(education)},
        {"id": "gallery", "label": "Gallery", "on": bool(gallery)},
        {"id": "achievements", "label": "Achievements", "on": bool(achievements)},
        {"id": "contact", "label": "Contact", "on": True},
    ]
    nav = [n for n in nav if n["on"]]

    return {
        "person": graph.person,
        "bio_html": render_block(bio_block),
        "tagline": top_skills or "Developer",
        "skill_groups": skill_groups,
        "projects": projects,
        "timeline": timeline,
        "education": education,
        "achievements": achievements,
        "analytics": analytics,
        "repositories": repositories or [],
        "gallery": gallery or [],
        "nav": nav,
        "resume_url": resume_url,
        "source_count": len(graph.documents) or 1,
        "meta_description": (
            f"{graph.person.name or 'Portfolio'} — "
            f"{len(projects)} projects, {len(skills)} skills."
        ),
    }

def render_portfolio(
    graph: ProfileGraph,
    config: ThemeConfig | None = None,
    analytics: dict | None = None,
    resume_url: str | None = None,
    repositories: list[dict] | None = None,
    gallery: list[dict] | None = None,
) -> str:
    """Produce a single self-contained HTML page (CSS and JS inlined)."""
    config = config or ThemeConfig()
    view = build_view_model(
        graph, analytics=analytics, resume_url=resume_url,
        repositories=repositories, gallery=gallery,
    )
    view["css"] = build_css(config)
    view["external_assets"] = False
    return TEMPLATE.render(**view)

def render_bundle(
    graph: ProfileGraph,
    config: ThemeConfig | None = None,
    analytics: dict | None = None,
    repositories: list[dict] | None = None,
    gallery: list[dict] | None = None,
) -> dict[str, str]:
    """Produce a conventional static site: separate HTML, CSS and JS.

    Returns {relative_path: text}. Gallery images are *not* included here —
    the caller copies the binary files into `images/` — but the markup already
    points at `images/<filename>`, so the two halves line up.
    """
    config = config or ThemeConfig()

    # Rewrite gallery URLs to the paths they will occupy inside the zip.
    local_gallery = []
    for item in gallery or []:
        entry = dict(item)
        entry["url"] = f"images/{item['filename']}"
        entry["link"] = None          # no server to link back to
        local_gallery.append(entry)

    view = build_view_model(
        graph, analytics=analytics, resume_url=None,
        repositories=repositories, gallery=local_gallery,
    )
    view["css"] = build_css(config)
    view["external_assets"] = True

    return {
        "index.html": TEMPLATE.render(**view),
        "style.css": build_css(config).strip() + "\n",
        "script.js": PORTFOLIO_JS,
    }