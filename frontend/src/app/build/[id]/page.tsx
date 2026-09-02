"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { GalleryManager } from "@/components/GalleryManager";
import { ProvenanceViewer } from "@/components/ProvenanceViewer";
import { ThemeStudio } from "@/components/ThemeStudio";
import { Banner, Logo, Spinner, Stat, ThemeToggle } from "@/components/ui";
import {
  type Conflict,
  type Gap,
  type Metrics,
  type Palette,
  type ProvenanceResponse,
  exportUrl,
  getProfile,
  getProvenance,
  previewUrl,
  resolveConflict,
} from "@/lib/api";

type Tab = "preview" | "provenance" | "conflicts" | "gallery" | "design";

const TABS: { key: Tab; label: string }[] = [
  { key: "preview", label: "Preview" },
  { key: "provenance", label: "Provenance" },
  { key: "conflicts", label: "Conflicts" },
  { key: "gallery", label: "Gallery" },
  { key: "design", label: "Design" },
];

export default function BuildPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  const [tab, setTab] = useState<Tab>("preview");
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [name, setName] = useState<string | null>(null);
  const [theme, setTheme] = useState("minimal");
  const [overrides, setOverrides] = useState<Record<string, Palette>>({});
  const [provenance, setProvenance] = useState<ProvenanceResponse | null>(null);
  const [bust, setBust] = useState(Date.now());
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([getProfile(id), getProvenance(id)])
      .then(([profile, prov]) => {
        setMetrics(profile.metrics);
        setConflicts(profile.graph.conflicts ?? []);
        setGaps(profile.graph.gaps ?? []);
        setName(profile.graph.person?.name ?? null);
        setTheme(profile.theme?.theme ?? "minimal");
        setOverrides(profile.theme?.overrides ?? {});
        setProvenance(prov);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Load failed"))
      .finally(() => setLoading(false));
  }, [id]);

  const refreshPreview = useCallback(() => setBust(Date.now()), []);

  async function pick(conflictId: string, value: string) {
    await resolveConflict(id, conflictId, value);
    setConflicts((cs) =>
      cs.map((c) => (c.id === conflictId ? { ...c, resolved_value: value } : c))
    );
  }

  if (loading) {
    return (
      <main className="grid min-h-dvh place-items-center">
        <div className="flex items-center gap-3 text-fg-muted">
          <Spinner size={20} /> Loading your profile…
        </div>
      </main>
    );
  }

  if (error) {
    return (
      <main className="mx-auto max-w-xl px-6 py-24">
        <Banner tone="danger" title="Could not load this build">
          {error}
        </Banner>
        <Link href="/" className="btn btn-ghost mt-5">
          Start over
        </Link>
      </main>
    );
  }

  const unresolved = conflicts.filter((c) => !c.resolved_value).length;

  return (
    <main className="min-h-dvh">
      <header className="sticky top-0 z-20 border-b border-border bg-bg/85 backdrop-blur-lg">
        <div className="mx-auto max-w-7xl px-6">
          <div className="flex items-center justify-between py-3.5">
            <div className="flex items-center gap-4">
              <Link href="/">
                <Logo size={26} />
              </Link>
              {name && (
                <span className="hidden text-[13.5px] text-fg-muted sm:block">
                  / {name}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <a
                href={exportUrl(id)}
                className="btn btn-primary !py-2"
                download
                title="index.html, style.css, script.js and your gallery images"
              >
                Download site (.zip)
              </a>
              <ThemeToggle />
            </div>
          </div>

          <nav className="flex gap-1 overflow-x-auto" role="tablist">
            {TABS.map((t) => {
              const on = tab === t.key;
              return (
                <button
                  key={t.key}
                  role="tab"
                  aria-selected={on}
                  onClick={() => setTab(t.key)}
                  className="relative whitespace-nowrap px-3.5 py-2.5 text-[13.5px] font-medium transition-colors"
                  style={{ color: on ? "var(--fg)" : "var(--fg-muted)" }}
                >
                  {t.label}
                  {t.key === "conflicts" && unresolved > 0 && (
                    <span className="ml-1.5 rounded-full bg-warn-tint px-1.5 py-0.5 text-[10.5px] font-bold text-warn">
                      {unresolved}
                    </span>
                  )}
                  {on && (
                    <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent" />
                  )}
                </button>
              );
            })}
          </nav>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-6 py-6">
        {/* metrics */}
        {metrics && (
          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Stat value={metrics.claims} label="Claims" />
            <Stat
              value={metrics.multi_source_claims}
              label="Multi-source"
              tone="good"
            />
            <Stat value={metrics.about_words} label="About words" />
            <Stat value={metrics.llm_calls} label="LLM calls" tone="good" />
            <Stat
              value={conflicts.length}
              label="Conflicts"
              tone={conflicts.length ? "warn" : "default"}
            />
            <Stat value={`${metrics.elapsed_seconds}s`} label="Build time" />
          </div>
        )}

        {metrics && !metrics.llm_available && (
          <div className="mb-6">
            <Banner tone="warn" title="Built without a Groq API key">
              Extraction used heuristics and descriptions were passed through
              unchanged. Add <code className="font-mono text-[12px]">GROQ_API_KEY</code>{" "}
              to <code className="font-mono text-[12px]">backend/.env</code>,
              restart, and rebuild to see grounded rewriting.
            </Banner>
          </div>
        )}

        {/* ---- preview ---- */}
        {tab === "preview" && (
          <div className="fade-up card overflow-hidden">
            <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
              <span className="flex gap-1.5">
                {["#ef4444", "#f59e0b", "#22c55e"].map((c) => (
                  <span
                    key={c}
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ background: c, opacity: 0.75 }}
                  />
                ))}
              </span>
              <span className="ml-2 truncate font-mono text-[12px] text-fg-subtle">
                {(name ?? "portfolio").toLowerCase().replace(/\s+/g, "-")}.html
              </span>
              <a
                href={previewUrl(id, bust)}
                target="_blank"
                rel="noopener"
                className="ml-auto text-[12.5px] font-medium text-fg-muted hover:text-accent"
              >
                Open full page ↗
              </a>
            </div>
            <iframe
              key={bust}
              src={previewUrl(id, bust)}
              title="Portfolio preview"
              className="h-[74vh] w-full bg-white"
            />
          </div>
        )}

        {/* ---- provenance ---- */}
        {tab === "provenance" && provenance && (
          <div className="fade-up">
            <ProvenanceViewer buildId={id} data={provenance} />
          </div>
        )}

        {/* ---- conflicts & gaps ---- */}
        {tab === "conflicts" && (
          <div className="fade-up space-y-6">
            <section>
              <h2 className="mb-1 text-[15px] font-semibold">Contradictions</h2>
              <p className="mb-3 text-[13px] text-fg-muted">
                Where sources disagree the higher-priority one already wins
                automatically — <b>résumé → LinkedIn → GitHub → cover letter</b>.
                Override any choice below.
              </p>

              {conflicts.length === 0 ? (
                <div className="card p-8 text-center">
                  <svg className="mx-auto mb-2" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M20 6L9 17l-5-5" />
                  </svg>
                  <p className="text-[13.5px] font-medium">
                    No contradictions found
                  </p>
                  <p className="mt-1 text-[12.5px] text-fg-subtle">
                    Your sources agree on dates, titles and organisations.
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  {conflicts.map((c) => (
                    <div key={c.id} className="card p-5">
                      <div className="mb-1 flex items-center gap-2">
                        <span className="font-mono text-[11.5px] text-fg-subtle">
                          {c.field}
                        </span>
                        {c.resolved_value && (
                          <span className="chip" style={{ color: "var(--accent)" }}>
                            resolved
                          </span>
                        )}
                      </div>
                      <p className="mb-3 text-[14px] font-medium">
                        {c.description}
                      </p>
                      <div className="grid gap-2 sm:grid-cols-2">
                        {c.options.map((o, oi) => {
                          const chosen = c.resolved_value === o.value;
                          return (
                            <button
                              key={o.value}
                              onClick={() => pick(c.id, o.value)}
                              className="rounded-xl border-2 p-3 text-left transition-colors"
                              style={{
                                borderColor: chosen
                                  ? "var(--accent)"
                                  : "var(--border)",
                                background: chosen
                                  ? "var(--accent-tint)"
                                  : "var(--bg)",
                              }}
                            >
                              <div className="flex flex-wrap items-center gap-1.5 text-[13.5px] font-semibold">
                                {o.value}
                                {oi === 0 && (
                                  <span className="rounded-full bg-accent-tint px-1.5 py-0.5 text-[10px] font-bold text-accent">
                                    highest priority
                                  </span>
                                )}
                              </div>
                              <div className="mt-1 line-clamp-2 text-[12px] text-fg-subtle">
                                “{o.evidence.raw_text}”
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

          </div>
        )}

        {/* ---- gallery ---- */}
        {tab === "gallery" && (
          <div className="fade-up grid gap-5 xl:grid-cols-[1fr_400px]">
            <div>
              <h2 className="mb-1 text-[15px] font-semibold">Photo gallery</h2>
              <p className="mb-4 text-[13px] text-fg-muted">
                Upload your own photos — hackathons, demos, talks, team moments.
                Click any caption to edit it. Images are stored with this build
                and embedded directly into the exported HTML.
              </p>
              <GalleryManager buildId={id} onChanged={refreshPreview} />
            </div>
            <aside className="xl:sticky xl:top-32 xl:self-start">
              <div className="card overflow-hidden">
                <div className="border-b border-border px-4 py-2.5 text-[12px] font-semibold uppercase tracking-[0.08em] text-fg-subtle">
                  Live preview
                </div>
                <iframe
                  key={bust}
                  src={previewUrl(id, bust)}
                  title="Gallery preview"
                  className="h-[62vh] w-full bg-white"
                />
              </div>
            </aside>
          </div>
        )}

        {/* ---- design ---- */}
        {tab === "design" && (
          <div className="fade-up grid gap-5 xl:grid-cols-[1fr_400px]">
            <ThemeStudio
              buildId={id}
              initialTheme={theme}
              initialOverrides={overrides}
              onApplied={refreshPreview}
            />
            <aside className="xl:sticky xl:top-32 xl:self-start">
              <div className="card overflow-hidden">
                <div className="border-b border-border px-4 py-2.5 text-[12px] font-semibold uppercase tracking-[0.08em] text-fg-subtle">
                  Live preview
                </div>
                <iframe
                  key={bust}
                  src={previewUrl(id, bust)}
                  title="Live theme preview"
                  className="h-[62vh] w-full bg-white"
                />
              </div>
            </aside>
          </div>
        )}
      </div>
    </main>
  );
}
