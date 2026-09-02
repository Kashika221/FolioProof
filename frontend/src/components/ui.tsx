"use client";

import { useEffect, useState } from "react";

/** Wordmark. The tick is the whole thesis in one glyph. */
export function Logo({ size = 30 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <svg
        width={size}
        height={size}
        viewBox="0 0 32 32"
        fill="none"
        aria-hidden="true"
      >
        <rect
          x="1.25"
          y="1.25"
          width="29.5"
          height="29.5"
          rx="9"
          stroke="var(--accent)"
          strokeWidth="2.5"
        />
        <path
          d="M9 16.6L13.8 21.4L23 10.8"
          stroke="var(--accent)"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span className="text-[19px] font-bold tracking-[-0.02em]">
        Folio<span className="text-accent">Proof</span>
      </span>
    </span>
  );
}

export function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("fp-theme", next ? "dark" : "light");
    } catch {
      /* private mode */
    }
  }

  return (
    <button
      onClick={toggle}
      className="btn btn-ghost !px-3 !py-2"
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={dark ? "Light mode" : "Dark mode"}
    >
      {dark ? (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" />
        </svg>
      )}
    </button>
  );
}

/** Which source backs a sentence, tinted by its precedence rank. */
export function SourcePill({ source }: { source: string | null }) {
  const map: Record<string, { label: string; fg: string; bg: string }> = {
    resume: { label: "Résumé", fg: "var(--accent)", bg: "var(--accent-tint)" },
    linkedin: { label: "LinkedIn", fg: "var(--info)", bg: "rgba(37,99,235,0.12)" },
    github: { label: "GitHub", fg: "var(--fg-muted)", bg: "var(--surface-2)" },
    cover_letter: { label: "Cover letter", fg: "var(--warn)", bg: "var(--warn-tint)" },
  };
  const m = map[source ?? ""] ?? {
    label: "No source",
    fg: "var(--fg-subtle)",
    bg: "var(--surface-2)",
  };

  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold"
      style={{ background: m.bg, color: m.fg }}
      title={source ? `Highest-priority source backing this sentence: ${m.label}` : undefined}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: m.fg }} />
      {m.label}
    </span>
  );
}

export function Stat({
  value,
  label,
  tone = "default",
}: {
  value: string | number;
  label: string;
  tone?: "default" | "good" | "warn" | "bad";
}) {
  const colour = {
    default: "var(--fg)",
    good: "var(--accent)",
    warn: "var(--warn)",
    bad: "var(--danger)",
  }[tone];

  return (
    <div className="card p-4">
      <div
        className="text-[26px] font-bold leading-none tracking-[-0.02em]"
        style={{ color: colour }}
      >
        {value}
      </div>
      <div className="mt-1.5 text-[11.5px] font-medium uppercase tracking-[0.07em] text-fg-subtle">
        {label}
      </div>
    </div>
  );
}

export function Banner({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "warn" | "danger";
  title: string;
  children?: React.ReactNode;
}) {
  const styles = {
    info: { bg: "var(--accent-tint)", bd: "var(--accent)", fg: "var(--accent)" },
    warn: { bg: "var(--warn-tint)", bd: "var(--warn)", fg: "var(--warn)" },
    danger: { bg: "var(--danger-tint)", bd: "var(--danger)", fg: "var(--danger)" },
  }[tone];

  return (
    <div
      className="rounded-2xl border p-4"
      style={{ background: styles.bg, borderColor: styles.bd }}
    >
      <div className="text-[13.5px] font-semibold" style={{ color: styles.fg }}>
        {title}
      </div>
      {children && (
        <div className="mt-1 text-[13px] leading-relaxed text-fg-muted">
          {children}
        </div>
      )}
    </div>
  );
}

export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      className="animate-spin"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.25" fill="none" />
      <path d="M21 12a9 9 0 00-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" fill="none" />
    </svg>
  );
}
