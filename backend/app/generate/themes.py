"""Four themes, each with independently recolourable sections.

Design decision that makes per-section colour work: the renderer never writes a
literal colour into a rule. Every section reads its palette from CSS custom
properties scoped to that section:

    [data-section="projects"] { --bg: ...; --fg: ...; --accent: ...; }

So a theme is a *stylesheet plus a default palette per section*, and a user
override is just a different set of custom properties for one section. Changing
the projects background from cream to charcoal touches three variables and no
layout code — which is why the theme picker and the colour pickers compose
instead of multiplying into 4 x N hand-written variants.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
import re

SECTIONS = ["hero", "about", "skills", "projects", "repositories", "experience",
            "education", "github", "gallery", "achievements", "contact"]

HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class SectionPalette(BaseModel):
    bg: str
    fg: str
    accent: str
    muted: str | None = None

    @field_validator("bg", "fg", "accent", "muted")
    @classmethod
    def _validate_hex(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not HEX_RE.match(v):
            raise ValueError(f"invalid hex colour: {v!r}")
        return v.lower()


class Theme(BaseModel):
    key: str
    label: str
    description: str
    font_stack: str
    heading_stack: str
    radius: str
    palettes: dict[str, SectionPalette]
    extra_css: str = ""


def _p(bg: str, fg: str, accent: str, muted: str | None = None) -> SectionPalette:
    return SectionPalette(bg=bg, fg=fg, accent=accent, muted=muted)


# ---------------------------------------------------------------------------
# 1. Minimal -- editorial whitespace, quiet type
# ---------------------------------------------------------------------------

MINIMAL = Theme(
    key="minimal",
    label="Minimal",
    description="Generous whitespace, restrained type, a single accent colour.",
    font_stack="'Inter', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif",
    heading_stack="'Inter', ui-sans-serif, system-ui, sans-serif",
    radius="10px",
    palettes={
        "hero": _p("#ffffff", "#111418", "#2563eb", "#5b6472"),
        "about": _p("#ffffff", "#1f2429", "#2563eb", "#5b6472"),
        "skills": _p("#f7f8fa", "#1f2429", "#2563eb", "#5b6472"),
        "projects": _p("#ffffff", "#1f2429", "#2563eb", "#5b6472"),
        "repositories": _p("#f7f8fa", "#1f2429", "#2563eb", "#5b6472"),
        "experience": _p("#f7f8fa", "#1f2429", "#2563eb", "#5b6472"),
        "education": _p("#ffffff", "#1f2429", "#2563eb", "#5b6472"),
        "github": _p("#f7f8fa", "#1f2429", "#2563eb", "#5b6472"),
        "achievements": _p("#ffffff", "#1f2429", "#2563eb", "#5b6472"),
        "contact": _p("#111418", "#f4f6f8", "#7aa2ff", "#9aa4b2"),
        "gallery": _p("#ffffff", "#1f2429", "#2563eb", "#5b6472"),},
    extra_css="""
.hero h1 { letter-spacing: -0.03em; }
.section { border-top: 1px solid color-mix(in srgb, var(--fg) 8%, transparent); }
.card { border: 1px solid color-mix(in srgb, var(--fg) 12%, transparent); }
""",
)

# ---------------------------------------------------------------------------
# 2. Playful -- warm coral/teal/yellow, floating shapes, springy motion
# ---------------------------------------------------------------------------
#
# Palette from the reference design:
#   coral  #ff6b6b   teal  #4ecdc4   yellow #ffe66d
#   ground #fff5f5   ink   #2d3748
# The three brand colours rotate as the per-section accent so scrolling the page
# cycles coral -> teal -> yellow instead of repeating one hue.

PLAYFUL = Theme(
    key="playful",
    label="Playful",
    description="Warm coral, teal and yellow with floating shapes and springy motion.",
    font_stack="'Poppins', 'Nunito', ui-rounded, ui-sans-serif, system-ui, sans-serif",
    heading_stack="'Poppins', 'Nunito', ui-rounded, ui-sans-serif, sans-serif",
    radius="24px",
    palettes={
        "hero": _p("#fff5f5", "#2d3748", "#ff6b6b", "#718096"),
        "about": _p("#ffffff", "#2d3748", "#4ecdc4", "#718096"),
        "skills": _p("#fff5f5", "#2d3748", "#ffb03a", "#718096"),
        "projects": _p("#ffffff", "#2d3748", "#ff6b6b", "#718096"),
        "repositories": _p("#f0fdfa", "#2d3748", "#4ecdc4", "#718096"),
        "experience": _p("#fff5f5", "#2d3748", "#ff6b6b", "#718096"),
        "education": _p("#ffffff", "#2d3748", "#4ecdc4", "#718096"),
        "github": _p("#fffbeb", "#2d3748", "#ffb03a", "#718096"),
        "gallery": _p("#ffffff", "#2d3748", "#ff6b6b", "#718096"),
        "achievements": _p("#fff5f5", "#2d3748", "#4ecdc4", "#718096"),
        "contact": _p("#2d3748", "#fff5f5", "#ffe66d", "#a0aec0"),
    },
    extra_css="""
/* Floating shapes, drawn per-section so they inherit that section's accent.
   Done with pseudo-elements rather than extra markup so the theme stays a
   stylesheet swap -- no template branch, no DOM for the other three themes. */
.section::before,
.section::after {
  content: ""; position: absolute; pointer-events: none; border-radius: 50%;
  filter: blur(0.5px); opacity: 0.5; z-index: 0;
}
.section::before {
  width: 120px; height: 120px; top: 8%; left: -40px;
  background: linear-gradient(45deg, var(--accent), color-mix(in srgb, var(--accent) 30%, #4ecdc4));
  animation: floaty 7s ease-in-out infinite;
}
.section::after {
  width: 76px; height: 76px; bottom: 12%; right: -24px;
  background: linear-gradient(45deg, #ffe66d, var(--accent));
  animation: floaty 9s ease-in-out infinite reverse;
}
.section-inner { z-index: 1; }

@keyframes floaty {
  0%, 100% { transform: translateY(0) rotate(0deg); }
  33%      { transform: translateY(-24px) rotate(120deg); }
  66%      { transform: translateY(20px) rotate(240deg); }
}

.hero h1 {
  background: linear-gradient(135deg, #ff6b6b, #4ecdc4);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
}
.hero .headline { color: var(--muted); font-weight: 500; }

.section-title {
  font-size: 15px; letter-spacing: 0.1em;
  display: inline-block; position: relative; padding-bottom: 10px;
}
.section-title::after {
  content: ""; position: absolute; left: 0; bottom: 0;
  width: 100%; height: 4px; border-radius: 999px;
  background: linear-gradient(135deg, var(--accent), #ffe66d);
}

.card {
  background: #ffffff;
  border: 2px solid color-mix(in srgb, var(--accent) 22%, transparent);
  box-shadow: 0 10px 26px color-mix(in srgb, var(--accent) 14%, transparent);
  transition: transform 260ms cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 260ms ease;
}
.card:hover {
  transform: translateY(-8px) rotate(-1deg);
  box-shadow: 0 22px 46px color-mix(in srgb, var(--accent) 24%, transparent);
}

.chip {
  background: color-mix(in srgb, var(--accent) 16%, #ffffff);
  border: 1.5px solid color-mix(in srgb, var(--accent) 34%, transparent);
  font-weight: 600;
}

.btn {
  background: linear-gradient(135deg, #ff6b6b, #4ecdc4);
  color: #ffffff; border: none; font-weight: 700;
  box-shadow: 0 8px 22px rgba(255, 107, 107, 0.32);
}
.btn:hover { animation: pop 0.5s ease-in-out; }
.btn.ghost {
  background: transparent; color: var(--accent);
  border: 2px solid var(--accent); box-shadow: none;
}
.btn.ghost:hover { background: var(--accent); color: #ffffff; }

@keyframes pop {
  0%, 100% { transform: scale(1); }
  50%      { transform: scale(1.06); }
}

.timeline::before { width: 4px; border-radius: 999px;
  background: linear-gradient(to bottom, #ff6b6b, #ffe66d); }
.timeline .item::before {
  width: 15px; height: 15px; left: -26px;
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 24%, transparent);
}

.stat .n { font-size: 34px; }
.shot { border: 3px solid color-mix(in srgb, var(--accent) 30%, transparent); }
.shot:hover { animation: wiggle 0.5s ease-in-out; }

@keyframes wiggle {
  0%, 100% { transform: rotate(0deg); }
  25%      { transform: rotate(-2deg); }
  75%      { transform: rotate(2deg); }
}

@media (prefers-reduced-motion: reduce) {
  .section::before, .section::after { animation: none; }
}
""",
)

# ---------------------------------------------------------------------------
# 3. Terminal -- monospace developer dashboard
# ---------------------------------------------------------------------------

TERMINAL = Theme(
    key="terminal",
    label="Developer Terminal",
    description="Monospace, dense, high-contrast. Reads like a well-kept dotfile.",
    font_stack="'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    heading_stack="'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace",
    radius="4px",
    palettes={
        "hero": _p("#0b0f0c", "#c8f7d4", "#3ddc84", "#6f8f7a"),
        "about": _p("#0d120f", "#d3ffe2", "#3ddc84", "#6f8f7a"),
        "skills": _p("#0b0f0c", "#d3ffe2", "#f5c542", "#6f8f7a"),
        "projects": _p("#0d120f", "#d3ffe2", "#3ddc84", "#6f8f7a"),
        "repositories": _p("#0b0f0c", "#d3ffe2", "#56b6ff", "#6f8f7a"),
        "experience": _p("#0b0f0c", "#d3ffe2", "#56b6ff", "#6f8f7a"),
        "education": _p("#0d120f", "#d3ffe2", "#3ddc84", "#6f8f7a"),
        "github": _p("#0b0f0c", "#d3ffe2", "#f5c542", "#6f8f7a"),
        "achievements": _p("#0d120f", "#d3ffe2", "#ff7b72", "#6f8f7a"),
        "contact": _p("#0b0f0c", "#c8f7d4", "#3ddc84", "#6f8f7a"),
        "gallery": _p("#0d120f", "#d3ffe2", "#f5c542", "#6f8f7a"),},
    extra_css="""
.section-title::before { content: "$ "; color: var(--accent); }
.card { border: 1px solid color-mix(in srgb, var(--accent) 34%, transparent); }
.card::before {
  content: "// " attr(data-index); display: block; font-size: 11px;
  color: var(--muted); margin-bottom: 6px;
}
.chip { border: 1px dashed color-mix(in srgb, var(--accent) 50%, transparent); }
a { text-decoration: underline; text-underline-offset: 3px; }
""",
)

# ---------------------------------------------------------------------------
# 4. Academic -- serif, research-profile feel
# ---------------------------------------------------------------------------

ACADEMIC = Theme(
    key="academic",
    label="Academic",
    description="Serif body text and a formal rhythm, suited to research profiles.",
    font_stack="'Source Serif 4', Georgia, 'Times New Roman', serif",
    heading_stack="'Source Serif 4', Georgia, 'Times New Roman', serif",
    radius="2px",
    palettes={
        "hero": _p("#fbf9f4", "#1c1a17", "#7c2d12", "#6b6459"),
        "about": _p("#ffffff", "#1c1a17", "#7c2d12", "#6b6459"),
        "skills": _p("#fbf9f4", "#1c1a17", "#7c2d12", "#6b6459"),
        "projects": _p("#ffffff", "#1c1a17", "#7c2d12", "#6b6459"),
        "repositories": _p("#fbf9f4", "#1c1a17", "#7c2d12", "#6b6459"),
        "experience": _p("#fbf9f4", "#1c1a17", "#7c2d12", "#6b6459"),
        "education": _p("#ffffff", "#1c1a17", "#7c2d12", "#6b6459"),
        "github": _p("#fbf9f4", "#1c1a17", "#7c2d12", "#6b6459"),
        "achievements": _p("#ffffff", "#1c1a17", "#7c2d12", "#6b6459"),
        "contact": _p("#1c1a17", "#f5f1e8", "#d98f5a", "#a89f90"),
        "gallery": _p("#ffffff", "#1c1a17", "#7c2d12", "#6b6459"),},
    extra_css="""
.section-title {
  font-variant: small-caps; letter-spacing: 0.08em;
  border-bottom: 2px solid var(--accent); display: inline-block; padding-bottom: 4px;
}
.card { border-left: 3px solid color-mix(in srgb, var(--accent) 60%, transparent); }
.hero h1 { font-weight: 600; }
body { line-height: 1.75; }
""",
)


THEMES: dict[str, Theme] = {t.key: t for t in (MINIMAL, PLAYFUL, TERMINAL, ACADEMIC)}

# Builds saved before a theme was renamed still carry the old key. Map them
# rather than 500-ing when an old profile is loaded.
LEGACY_THEME_KEYS = {"glass": "playful", "glassmorphism": "playful"}


class ThemeConfig(BaseModel):
    """A theme choice plus optional per-section colour overrides."""

    theme: str = "minimal"
    overrides: dict[str, SectionPalette] = Field(default_factory=dict)

    @field_validator("theme")
    @classmethod
    def _known_theme(cls, v: str) -> str:
        v = LEGACY_THEME_KEYS.get(v, v)
        if v not in THEMES:
            raise ValueError(f"unknown theme {v!r}; choose from {sorted(THEMES)}")
        return v

    @field_validator("overrides")
    @classmethod
    def _known_sections(cls, v: dict[str, SectionPalette]) -> dict[str, SectionPalette]:
        bad = set(v) - set(SECTIONS)
        if bad:
            raise ValueError(f"unknown section(s): {sorted(bad)}; valid: {SECTIONS}")
        return v

    def resolved(self) -> tuple[Theme, dict[str, SectionPalette]]:
        """Theme defaults with the user's per-section overrides applied."""
        theme = THEMES[self.theme]
        palettes = dict(theme.palettes)
        for section, palette in self.overrides.items():
            palettes[section] = palette
        return theme, palettes


def build_css(config: ThemeConfig) -> str:
    """Emit the stylesheet: shared layout + per-section custom properties."""
    theme, palettes = config.resolved()

    blocks = []
    for section in SECTIONS:
        p = palettes.get(section)
        if not p:
            continue
        muted = p.muted or "color-mix(in srgb, var(--fg) 62%, var(--bg))"
        blocks.append(
            f'[data-section="{section}"] {{\n'
            f"  --bg: {p.bg};\n  --fg: {p.fg};\n  --accent: {p.accent};\n  --muted: {muted};\n"
            f"}}"
        )

    return f"""
:root {{
  --font-body: {theme.font_stack};
  --font-head: {theme.heading_stack};
  --radius: {theme.radius};
  --maxw: 980px;
}}

* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0; font-family: var(--font-body); line-height: 1.65;
  -webkit-font-smoothing: antialiased;
}}
img {{ max-width: 100%; display: block; }}
a {{ color: var(--accent); }}

{chr(10).join(blocks)}

.section {{
  position: relative; background: var(--bg); color: var(--fg);
  padding: 72px 24px; overflow: hidden;
}}
.section-inner {{ position: relative; max-width: var(--maxw); margin: 0 auto; }}
.section-title {{
  font-family: var(--font-head); font-size: 13px; text-transform: uppercase;
  letter-spacing: 0.14em; color: var(--accent); margin: 0 0 24px;
}}

.hero {{ padding: 104px 24px 88px; }}
.hero h1 {{
  font-family: var(--font-head); font-size: clamp(34px, 6vw, 60px);
  margin: 0 0 12px; line-height: 1.05;
}}
.hero .headline {{ font-size: clamp(16px, 2.2vw, 21px); color: var(--muted); margin: 0 0 26px; max-width: 62ch; }}
.hero .links {{ display: flex; flex-wrap: wrap; gap: 12px; }}

.btn {{
  display: inline-block; padding: 10px 18px; border-radius: var(--radius);
  background: var(--accent); color: var(--bg); text-decoration: none;
  font-weight: 600; font-size: 14px;
}}
.btn.ghost {{
  background: transparent; color: var(--fg);
  border: 1px solid color-mix(in srgb, var(--fg) 28%, transparent);
}}

.grid {{ display: grid; gap: 18px; }}
.grid.two {{ grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }}
.grid.three {{ grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); }}

.card {{
  background: color-mix(in srgb, var(--fg) 4%, var(--bg));
  border-radius: var(--radius); padding: 20px;
}}
.card h3 {{ font-family: var(--font-head); margin: 0 0 8px; font-size: 18px; }}
.card p {{ margin: 0 0 12px; color: var(--muted); }}

.chip {{
  display: inline-block; padding: 5px 11px; margin: 0 6px 6px 0;
  border-radius: 999px; font-size: 13px;
  background: color-mix(in srgb, var(--accent) 14%, transparent);
  color: var(--fg);
}}
.chip[data-corroborated="true"]::after {{
  content: " ✓"; color: var(--accent); font-weight: 700;
}}

/* --- sticky section navigation ------------------------------------------ */
.topnav {{
  position: sticky; top: 0; z-index: 50;
  background: color-mix(in srgb, var(--bg, #fff) 88%, transparent);
  backdrop-filter: saturate(160%) blur(12px);
  -webkit-backdrop-filter: saturate(160%) blur(12px);
  border-bottom: 1px solid color-mix(in srgb, currentColor 12%, transparent);
}}
.topnav-inner {{
  max-width: var(--maxw); margin: 0 auto; padding: 10px 24px;
  display: flex; align-items: center; gap: 18px;
}}
.topnav-brand {{
  font-family: var(--font-head); font-weight: 700; font-size: 15px;
  text-decoration: none; letter-spacing: -0.01em; margin-right: auto;
}}
.topnav-links {{ display: flex; flex-wrap: wrap; gap: 4px; }}
.topnav-links a {{
  padding: 6px 11px; border-radius: 999px; font-size: 13.5px;
  text-decoration: none; opacity: 0.75; white-space: nowrap;
  transition: opacity 140ms ease, background 140ms ease;
}}
.topnav-links a:hover {{
  opacity: 1; background: color-mix(in srgb, currentColor 10%, transparent);
}}
.topnav-toggle {{
  display: none; background: none; border: 0; cursor: pointer;
  font-size: 20px; color: inherit; padding: 4px 8px;
}}
@media (max-width: 720px) {{
  .topnav-toggle {{ display: block; }}
  .topnav-links {{
    display: none; width: 100%; flex-direction: column; gap: 2px; padding-top: 8px;
  }}
  .topnav-links.open {{ display: flex; }}
  .topnav-inner {{ flex-wrap: wrap; }}
}}
/* Anchors must clear the sticky bar when jumped to. */
.section {{ scroll-margin-top: 64px; }}

/* --- repository cards ---------------------------------------------------- */
.repo-head {{
  display: flex; align-items: baseline; justify-content: space-between; gap: 12px;
}}
.repo-head h3 {{ margin: 0; }}
.repo-head a {{ text-decoration: none; }}
.repo-head a:hover {{ text-decoration: underline; }}
.repo-meta {{ font-size: 13px; color: var(--muted); white-space: nowrap; }}
.repo-langs {{ margin: 8px 0 4px; }}

/* --- gallery ------------------------------------------------------------- */
.gallery {{
  display: grid; gap: 14px;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
}}
.shot {{
  margin: 0; overflow: hidden; border-radius: var(--radius);
  border: 1px solid color-mix(in srgb, var(--fg) 14%, transparent);
}}
.shot img {{
  width: 100%; aspect-ratio: 16 / 9; object-fit: cover; display: block;
  transition: transform 320ms cubic-bezier(0.22, 1, 0.36, 1);
}}
.shot:hover img {{ transform: scale(1.04); }}

.timeline {{ position: relative; padding-left: 26px; }}
.timeline .org {{ font-size: 14px; font-weight: 600; opacity: 0.9; }}
.timeline::before {{
  content: ""; position: absolute; left: 7px; top: 6px; bottom: 6px; width: 2px;
  background: color-mix(in srgb, var(--accent) 40%, transparent);
}}
.timeline .item {{ position: relative; margin-bottom: 26px; }}
.timeline .item::before {{
  content: ""; position: absolute; left: -24px; top: 7px;
  width: 11px; height: 11px; border-radius: 50%;
  background: var(--accent);
}}
.timeline .when {{ font-size: 13px; color: var(--muted); }}

.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 14px; }}
.stat {{ text-align: center; padding: 18px 10px; border-radius: var(--radius);
        background: color-mix(in srgb, var(--fg) 5%, var(--bg)); }}
.stat .n {{ font-family: var(--font-head); font-size: 27px; font-weight: 700; color: var(--accent); }}
.stat .k {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }}

.langbar {{ display: flex; height: 10px; border-radius: 999px; overflow: hidden; margin: 18px 0 12px; }}
.langbar span {{ display: block; height: 100%; }}
.langkey {{ display: flex; flex-wrap: wrap; gap: 14px; font-size: 13px; color: var(--muted); }}
.langkey i {{ display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; }}

/* Provenance: every generated sentence can point back at its source. */
[data-provenance] {{ cursor: help; transition: background 120ms ease; }}
body.provenance-on [data-provenance] {{
  background: color-mix(in srgb, var(--accent) 20%, transparent);
  box-shadow: inset 0 -2px 0 var(--accent);
  border-radius: 3px;
}}


.footer-note {{ font-size: 12.5px; color: var(--muted); margin-top: 28px; }}

@media print {{
  .section {{ padding: 28px 0; }}
  .btn {{ display: none; }}
}}

{theme.extra_css}
"""
