"use client";

import { useMemo, useState } from "react";

import { SourcePill } from "@/components/ui";
import {
  SOURCE_PRIORITY,
  type EvidenceRef,
  type PDFLocator,
  type ProvenanceResponse,
  type SentenceRef,
  pageImageUrl,
} from "@/lib/api";

const isPdf = (e: EvidenceRef): e is EvidenceRef & { locator: PDFLocator } =>
  e.locator.kind === "pdf";

function prettyTarget(target: string) {
  if (target === "bio") return "About / hero paragraph";
  if (target.startsWith("project:")) return "Project description";
  return target;
}

/**
 * The demo centrepiece.
 *
 * Left: every sentence FolioProof generated, tagged with the source behind it.
 * Right: the exact region of the original PDF that supports the selected one.
 *
 * Boxes are positioned in percentages of the PDF page size rather than pixels,
 * so the overlay stays aligned at any rendered image scale or container width.
 */
export function ProvenanceViewer({
  buildId,
  data,
}: {
  buildId: string;
  data: ProvenanceResponse;
}) {
  const [selected, setSelected] = useState<{
    sentence: SentenceRef;
    key: string;
  } | null>(null);

  const pageSizeOf = useMemo(() => {
    const map = new Map<string, [number, number][]>();
    // Defensive: an older backend build may not send `documents` at all.
    (data.documents ?? []).forEach((d) => map.set(d.source_id, d.page_sizes));
    return map;
  }, [data.documents]);

  const totals = useMemo(() => {
    const all = data.blocks.flatMap((b) => b.sentences);
    const bySource: Record<string, number> = {};
    all.forEach((s) => {
      const k = s.source ?? "none";
      bySource[k] = (bySource[k] ?? 0) + 1;
    });
    return { total: all.length, bySource };
  }, [data.blocks]);

  const pdfEvidence = selected?.sentence.evidence.filter(isPdf) ?? [];
  const otherEvidence =
    selected?.sentence.evidence.filter((e) => !isPdf(e)) ?? [];
  const activePage = pdfEvidence[0]?.locator.page ?? 0;
  const activeSource = pdfEvidence[0]?.source ?? "resume";
  const sizes = pageSizeOf.get(activeSource) ?? [];
  const [pw, ph] = sizes[activePage] ?? [595, 842];

  const boxesOnPage = pdfEvidence.filter(
    (e) => e.locator.page === activePage && e.source === activeSource
  );

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_minmax(340px,460px)]">
      {/* ---- generated sentences ---- */}
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="chip">
            <b>{totals.total}</b> sentences
          </span>
          {SOURCE_PRIORITY.filter((s) => totals.bySource[s]).map((s, i) => (
            <span key={s} className="chip" title={`Source priority ${i + 1}`}>
              <b>{totals.bySource[s]}</b> from {s.replace("_", " ")}
            </span>
          ))}
        </div>

        {data.blocks.map((block) => (
          <div key={block.target} className="card p-5">
            <div className="mb-1 text-[11.5px] font-semibold uppercase tracking-[0.08em] text-fg-subtle">
              {prettyTarget(block.target)}
            </div>

            {block.original && (
              <p className="mb-3 border-l-2 border-border pl-3 text-[13px] italic leading-relaxed text-fg-subtle">
                Original: “{block.original.slice(0, 180)}
                {block.original.length > 180 ? "…" : ""}”
              </p>
            )}

            <p className="text-[14.5px] leading-[1.75]">
              {block.sentences.map((s, i) => {
                const key = `${block.target}#${i}`;
                return (
                  <span
                    key={key}
                    className="sentence"
                    data-source={s.source ?? ""}
                    data-active={selected?.key === key}
                    onClick={() => setSelected({ sentence: s, key })}
                    onMouseEnter={() => setSelected({ sentence: s, key })}
                    title="Click to see the source evidence"
                  >
                    {s.text}{" "}
                  </span>
                );
              })}
            </p>

          </div>
        ))}
      </div>

      {/* ---- evidence panel ---- */}
      <aside className="lg:sticky lg:top-24 lg:self-start">
        <div className="card overflow-hidden">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <span className="text-[12px] font-semibold uppercase tracking-[0.08em] text-fg-subtle">
              Source evidence
            </span>
            {selected && <SourcePill source={selected.sentence.source} />}
          </div>

          {!selected ? (
            <div className="px-4 py-14 text-center">
              <svg
                className="mx-auto mb-3"
                width="26"
                height="26"
                viewBox="0 0 24 24"
                fill="none"
                stroke="var(--fg-subtle)"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                <path d="M14 2v6h6M9 15h6M9 11h3" />
              </svg>
              <p className="text-[13.5px] font-medium">
                Hover any sentence on the left
              </p>
              <p className="mt-1 text-[12.5px] text-fg-subtle">
                The exact lines of your PDF that support it will be boxed here.
              </p>
            </div>
          ) : (
            <div className="space-y-3 p-4">
              {selected.sentence.note && (
                <p className="rounded-xl bg-warn-tint px-3 py-2 text-[12.5px] font-medium text-warn">
                  {selected.sentence.note}
                </p>
              )}

              {boxesOnPage.length > 0 && (
                <div>
                  <div className="mb-1.5 text-[11.5px] font-semibold uppercase tracking-[0.07em] text-fg-subtle">
                    {activeSource} · page {activePage + 1}
                  </div>
                  <div className="relative overflow-hidden rounded-xl border border-border bg-white">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={pageImageUrl(buildId, activeSource, activePage)}
                      alt={`Page ${activePage + 1} of your ${activeSource}`}
                      className="block w-full"
                    />
                    {boxesOnPage.map((e, i) => {
                      const l = e.locator;
                      return (
                        <span
                          key={i}
                          className="evidence-box"
                          style={{
                            left: `${(l.x0 / pw) * 100}%`,
                            top: `${(l.top / ph) * 100}%`,
                            width: `${((l.x1 - l.x0) / pw) * 100}%`,
                            height: `${((l.bottom - l.top) / ph) * 100}%`,
                          }}
                        />
                      );
                    })}
                  </div>
                </div>
              )}

              {selected.sentence.evidence.length === 0 && (
                <p className="py-6 text-center text-[13px] text-fg-subtle">
                  No evidence attached to this sentence.
                </p>
              )}

              {[...boxesOnPage, ...otherEvidence].slice(0, 5).map((e, i) => (
                <div
                  key={i}
                  className="rounded-xl border border-border bg-surface-2 p-3"
                >
                  <div className="mb-1 flex items-center gap-1.5">
                    <span className="text-[11px] font-bold uppercase tracking-[0.06em] text-accent">
                      {e.source}
                    </span>
                    {e.locator.kind === "github" && e.locator.repo && (
                      <span className="text-[11px] text-fg-subtle">
                        · {e.locator.repo} / {e.locator.field}
                      </span>
                    )}
                    {e.locator.kind === "pdf" && (
                      <span className="text-[11px] text-fg-subtle">
                        · page {e.locator.page + 1}
                      </span>
                    )}
                  </div>
                  <p className="text-[12.5px] leading-relaxed text-fg-muted">
                    {e.text}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
