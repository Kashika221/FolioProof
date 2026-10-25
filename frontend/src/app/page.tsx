"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { FileDrop } from "@/components/FileDrop";
import { Banner, Logo, Spinner, ThemeToggle } from "@/components/ui";
import { buildProfile, health } from "@/lib/api";

const STAGES = [
  "Reading your documents",
  "Fetching GitHub repositories",
  "Fusing sources into one profile",
  "Checking for contradictions",
  "Verifying every generated sentence",
];

export default function Home() {
  const router = useRouter();

  const [resume, setResume] = useState<File | null>(null);
  const [linkedin, setLinkedin] = useState<File | null>(null);
  const [coverLetter, setCoverLetter] = useState<File | null>(null);
  const [github, setGithub] = useState("");
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [groqReady, setGroqReady] = useState<boolean | null>(null);
  const [apiUp, setApiUp] = useState<boolean | null>(null);

  useEffect(() => {
    health()
      .then((h) => {
        setApiUp(true);
        setGroqReady(h.groq_configured);
      })
      .catch(() => setApiUp(false));
  }, []);

  // Advance the stage labels while the request is in flight. Purely
  // indicative — the backend is one call, not a streamed job queue.
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(
      () => setStage((s) => Math.min(s + 1, STAGES.length - 1)),
      1400
    );
    return () => clearInterval(t);
  }, [busy]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!resume) {
      setError("A résumé PDF is required.");
      return;
    }
    setBusy(true);
    setStage(0);
    setError(null);
    try {
      const res = await buildProfile({
        resume,
        linkedin,
        coverLetter,
        githubUsername: github.trim(),
      });
      router.push(`/build/${res.build_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Build failed.");
      setBusy(false);
    }
  }

  return (
    <main className="min-h-dvh">
      <header className="sticky top-0 z-20 border-b border-border bg-bg/85 backdrop-blur-lg">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3.5">
          <Logo />
          <div className="flex items-center gap-2">
            <a
              href="https://github.com"
              className="hidden text-[13.5px] font-medium text-fg-muted hover:text-fg sm:block"
            >
              How it works
            </a>
            <ThemeToggle />
          </div>
        </div>
      </header>

      {/* hero */}
      <section className="relative overflow-hidden">
        <div className="dotfield absolute inset-0 -z-10" aria-hidden="true" />
        <div className="mx-auto max-w-6xl px-6 pb-8 pt-20 text-center">
          <div className="fade-up mx-auto mb-6 inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3.5 py-1.5 text-[12.5px] font-medium">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" />
            Every sentence traceable to its source
          </div>

          <h1
            className="fade-up mx-auto max-w-4xl text-[clamp(38px,7vw,60px)] font-bold leading-[1.04] tracking-[-0.035em]"
            style={{ animationDelay: "60ms" }}
          >
            Your portfolio,
            <br />
            <span className="text-accent">proven line by line.</span>
          </h1>

          <p
            className="fade-up mx-auto mt-5 max-w-2xl text-[16.5px] leading-relaxed text-fg-muted"
            style={{ animationDelay: "120ms" }}
          >
            Most AI portfolio builders quietly invent skills you never had.
            FolioProof fuses your résumé, GitHub and LinkedIn into one
            consistent profile — and refuses to publish a sentence it cannot
            trace back to a document you gave it.
          </p>

          <div
            className="fade-up mt-7 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-[13px] text-fg-subtle"
            style={{ animationDelay: "180ms" }}
          >
            {[
              "Word-level provenance",
              "Contradiction detection",
              "4 themes, recolourable",
            ].map((t) => (
              <span key={t} className="inline-flex items-center gap-1.5">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 6L9 17l-5-5" />
                </svg>
                {t}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* form */}
      <section className="mx-auto max-w-3xl px-6 pb-24">
        <form
          onSubmit={submit}
          className="fade-up card p-6 shadow-[var(--shadow-lg)] sm:p-8"
          style={{ animationDelay: "240ms" }}
        >
          {apiUp === false && (
            <div className="mb-5">
              <Banner tone="danger" title="Backend not reachable">
                Start it with{" "}
                <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[12px]">
                  uvicorn app.main:app --port 8000
                </code>{" "}
                from the backend directory.
              </Banner>
            </div>
          )}

          {apiUp && groqReady === false && (
            <div className="mb-5">
              <Banner tone="warn" title="Running without a Groq API key">
                Extraction falls back to heuristics and text is passed through
                unchanged, so grounded rewriting and verification stay idle. Add{" "}
                <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[12px]">
                  GROQ_API_KEY
                </code>{" "}
                to <code className="font-mono text-[12px]">backend/.env</code> to
                enable them.
              </Banner>
            </div>
          )}

          <div className="grid gap-5 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <FileDrop
                label="Résumé"
                hint="Text-based PDF, up to 10 MB"
                file={resume}
                onFile={setResume}
                required
              />
            </div>
            <FileDrop
              label="LinkedIn export"
              hint="Profile → Save to PDF"
              file={linkedin}
              onFile={setLinkedin}
            />
            <FileDrop
              label="Cover letter"
              hint="Supplies tone and career intent"
              file={coverLetter}
              onFile={setCoverLetter}
            />
          </div>

          <div className="mt-5">
            <label
              htmlFor="gh"
              className="mb-2 block text-[13.5px] font-semibold"
            >
              GitHub username
              <span className="ml-2 text-[12px] font-normal text-fg-subtle">
                strongly recommended
              </span>
            </label>
            <div className="flex items-center gap-2 rounded-xl border border-border-strong bg-bg px-3.5 focus-within:border-accent focus-within:shadow-[0_0_0_3px_var(--accent-ring)]">
              <span className="text-[14.5px] text-fg-subtle">github.com/</span>
              <input
                id="gh"
                value={github}
                onChange={(e) => setGithub(e.target.value)}
                placeholder="your-username"
                autoComplete="off"
                spellCheck={false}
                className="w-full bg-transparent py-2.5 text-[14.5px] outline-none placeholder:text-fg-subtle"
              />
            </div>
            <p className="mt-1.5 text-[12.5px] text-fg-subtle">
              Your top repositories get their own section, and their languages
              enrich your skills list.
            </p>
          </div>

          {error && (
            <p className="mt-4 rounded-xl bg-danger-tint px-3.5 py-2.5 text-[13px] font-medium text-danger">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={busy || !resume || apiUp === false}
            className="btn btn-primary mt-6 w-full !py-3 !text-[15px]"
          >
            {busy ? (
              <>
                <Spinner /> {STAGES[stage]}…
              </>
            ) : (
              "Build my portfolio"
            )}
          </button>

          {busy && (
            <div className="mt-4 space-y-1.5">
              {STAGES.map((s, i) => (
                <div
                  key={s}
                  className="flex items-center gap-2.5 text-[12.5px] transition-opacity"
                  style={{ opacity: i <= stage ? 1 : 0.35 }}
                >
                  {i < stage ? (
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M20 6L9 17l-5-5" />
                    </svg>
                  ) : i === stage ? (
                    <span className="text-accent">
                      <Spinner size={13} />
                    </span>
                  ) : (
                    <span className="h-[13px] w-[13px] rounded-full border border-border-strong" />
                  )}
                  <span className={i <= stage ? "text-fg" : "text-fg-subtle"}>
                    {s}
                  </span>
                </div>
              ))}
            </div>
          )}
        </form>

        <p className="mt-5 text-center text-[12.5px] text-fg-subtle">
          Files stay on your machine — the backend runs locally.
        </p>
      </section>
    </main>
  );
}
