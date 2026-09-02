"use client";

import { useEffect, useMemo, useState } from "react";

import { type Palette, type ThemesResponse, getThemes, setTheme } from "@/lib/api";

const SECTION_LABELS: Record<string, string> = {
  hero: "Hero",
  about: "About",
  skills: "Skills",
  projects: "Projects",
  repositories: "Top Repositories",
  experience: "Experience",
  education: "Education",
  github: "GitHub Stats",
  gallery: "Gallery",
  achievements: "Achievements",
  contact: "Contact",
};

const SWATCH_KEYS: (keyof Pick<Palette, "bg" | "fg" | "accent">)[] = [
  "bg",
  "fg",
  "accent",
];

const SWATCH_LABELS = { bg: "Background", fg: "Text", accent: "Accent" };

/** Miniature of a theme, drawn from its own hero + projects palettes. */
function ThemeCard({
  info,
  active,
  onPick,
}: {
  info: ThemesResponse["themes"][number];
  active: boolean;
  onPick: () => void;
}) {
  const hero = info.palettes.hero;
  const projects = info.palettes.projects;

  return (
    <button
      onClick={onPick}
      className="group rounded-2xl border-2 p-2 text-left transition-all duration-150"
      style={{
        borderColor: active ? "var(--accent)" : "var(--border)",
        background: active ? "var(--accent-tint)" : "var(--bg)",
      }}
      aria-pressed={active}
    >
      <div
        className="mb-2 overflow-hidden rounded-xl border border-border"
        style={{ background: hero.bg }}
      >
        <div className="px-3 pb-2 pt-3">
          <div
            className="mb-1.5 h-2 w-2/3 rounded-full"
            style={{ background: hero.fg, opacity: 0.9 }}
          />
          <div
            className="mb-2.5 h-1.5 w-1/2 rounded-full"
            style={{ background: hero.muted ?? hero.fg, opacity: 0.45 }}
          />
          <div
            className="h-4 w-16 rounded-full"
            style={{ background: hero.accent }}
          />
        </div>
        <div className="flex gap-1.5 px-3 pb-3" style={{ background: projects.bg }}>
          {[0, 1].map((i) => (
            <div
              key={i}
              className="h-8 flex-1 rounded-md"
              style={{
                background: projects.fg,
                opacity: 0.09,
                border: `1px solid ${projects.accent}`,
              }}
            />
          ))}
        </div>
      </div>
      <div className="px-1 pb-1">
        <div className="flex items-center gap-1.5 text-[13.5px] font-semibold">
          {info.label}
          {active && (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 6L9 17l-5-5" />
            </svg>
          )}
        </div>
        <div className="mt-0.5 text-[11.5px] leading-snug text-fg-subtle">
          {info.description}
        </div>
      </div>
    </button>
  );
}

export function ThemeStudio({
  buildId,
  initialTheme,
  initialOverrides,
  onApplied,
}: {
  buildId: string;
  initialTheme: string;
  initialOverrides: Record<string, Palette>;
  onApplied: () => void;
}) {
  const [themes, setThemes] = useState<ThemesResponse | null>(null);
  const [theme, setThemeKey] = useState(initialTheme);
  const [overrides, setOverrides] =
    useState<Record<string, Palette>>(initialOverrides);
  const [openSection, setOpenSection] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getThemes().then(setThemes).catch(() => setThemes(null));
  }, []);

  const active = useMemo(
    () => themes?.themes.find((t) => t.key === theme) ?? null,
    [themes, theme]
  );

  // Debounced persist: colour inputs fire continuously while dragging.
  useEffect(() => {
    if (!themes) return;
    setSaving(true);
    const t = setTimeout(() => {
      setTheme(buildId, theme, overrides)
        .then(() => onApplied())
        .finally(() => setSaving(false));
    }, 320);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme, overrides, themes]);

  function paletteFor(section: string): Palette {
    return (
      overrides[section] ??
      active?.palettes[section] ?? { bg: "#ffffff", fg: "#111111", accent: "#22c55e", muted: null }
    );
  }

  function setColour(section: string, key: "bg" | "fg" | "accent", value: string) {
    const base = paletteFor(section);
    setOverrides((o) => ({
      ...o,
      [section]: { ...base, [key]: value },
    }));
  }

  function resetSection(section: string) {
    setOverrides((o) => {
      const next = { ...o };
      delete next[section];
      return next;
    });
  }

  if (!themes) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="skeleton h-44 rounded-2xl" />
        ))}
      </div>
    );
  }

  const customised = Object.keys(overrides);

  return (
    <div className="space-y-6">
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-[14px] font-semibold">Theme</h3>
          {saving && (
            <span className="text-[12px] text-fg-subtle">Applying…</span>
          )}
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {themes.themes.map((t) => (
            <ThemeCard
              key={t.key}
              info={t}
              active={t.key === theme}
              onPick={() => setThemeKey(t.key)}
            />
          ))}
        </div>
      </div>

      <div>
        <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-[14px] font-semibold">Section colours</h3>
          {customised.length > 0 && (
            <button
              onClick={() => setOverrides({})}
              className="text-[12.5px] font-medium text-fg-subtle hover:text-danger"
            >
              Reset all ({customised.length})
            </button>
          )}
        </div>
        <p className="mb-3 text-[12.5px] text-fg-subtle">
          Every section carries its own palette, so you can recolour one band of
          the page without touching the rest.
        </p>

        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {themes.sections.map((section) => {
            const p = paletteFor(section);
            const isOpen = openSection === section;
            const isCustom = section in overrides;

            return (
              <div
                key={section}
                className="rounded-2xl border p-3 transition-colors"
                style={{
                  borderColor: isCustom ? "var(--accent)" : "var(--border)",
                  background: "var(--surface)",
                }}
              >
                <button
                  onClick={() => setOpenSection(isOpen ? null : section)}
                  className="flex w-full items-center justify-between gap-2"
                  aria-expanded={isOpen}
                >
                  <span className="flex items-center gap-2">
                    <span className="flex -space-x-1">
                      {SWATCH_KEYS.map((k) => (
                        <span
                          key={k}
                          className="h-4 w-4 rounded-full border border-border"
                          style={{ background: p[k] }}
                        />
                      ))}
                    </span>
                    <span className="text-[13.5px] font-medium">
                      {SECTION_LABELS[section] ?? section}
                    </span>
                  </span>
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="var(--fg-subtle)"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    style={{
                      transform: isOpen ? "rotate(180deg)" : "none",
                      transition: "transform 160ms ease",
                    }}
                  >
                    <path d="M6 9l6 6 6-6" />
                  </svg>
                </button>

                {isOpen && (
                  <div className="mt-3 space-y-2 border-t border-border pt-3">
                    {SWATCH_KEYS.map((k) => (
                      <label
                        key={k}
                        className="flex items-center justify-between gap-2"
                      >
                        <span className="text-[12.5px] text-fg-muted">
                          {SWATCH_LABELS[k]}
                        </span>
                        <span className="flex items-center gap-2">
                          <code className="font-mono text-[11.5px] text-fg-subtle">
                            {p[k]}
                          </code>
                          <input
                            type="color"
                            value={p[k]}
                            onChange={(e) => setColour(section, k, e.target.value)}
                            className="h-7 w-9 cursor-pointer rounded-md border border-border bg-transparent p-0.5"
                            aria-label={`${SECTION_LABELS[section]} ${SWATCH_LABELS[k]}`}
                          />
                        </span>
                      </label>
                    ))}
                    {isCustom && (
                      <button
                        onClick={() => resetSection(section)}
                        className="mt-1 w-full rounded-lg py-1.5 text-[12px] font-medium text-fg-subtle hover:bg-surface-2 hover:text-danger"
                      >
                        Reset to theme default
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
