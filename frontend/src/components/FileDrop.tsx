"use client";

import { useCallback, useRef, useState } from "react";

export function FileDrop({
  label,
  hint,
  file,
  onFile,
  required = false,
}: {
  label: string;
  hint: string;
  file: File | null;
  onFile: (f: File | null) => void;
  required?: boolean;
}) {
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const accept = useCallback(
    (f: File | undefined) => {
      setError(null);
      if (!f) return;
      if (!f.name.toLowerCase().endsWith(".pdf")) {
        setError("Only PDF files are supported.");
        return;
      }
      if (f.size > 10 * 1024 * 1024) {
        setError("That file is over 10 MB.");
        return;
      }
      onFile(f);
    },
    [onFile]
  );

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <label className="text-[13.5px] font-semibold">
          {label}
          {required ? (
            <span className="ml-1 text-accent">*</span>
          ) : (
            <span className="ml-2 text-[12px] font-normal text-fg-subtle">
              optional
            </span>
          )}
        </label>
        {file && (
          <button
            type="button"
            onClick={() => {
              onFile(null);
              if (inputRef.current) inputRef.current.value = "";
            }}
            className="text-[12px] font-medium text-fg-subtle hover:text-danger"
          >
            Remove
          </button>
        )}
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          accept(e.dataTransfer.files?.[0]);
        }}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        role="button"
        tabIndex={0}
        aria-label={`${label}: choose a PDF file or drag one here`}
        className="cursor-pointer rounded-2xl border-2 border-dashed p-5 text-center transition-all duration-150"
        style={{
          borderColor: error
            ? "var(--danger)"
            : over
            ? "var(--accent)"
            : file
            ? "var(--accent)"
            : "var(--border-strong)",
          background: over
            ? "var(--accent-tint)"
            : file
            ? "var(--accent-tint)"
            : "var(--bg)",
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          onChange={(e) => accept(e.target.files?.[0])}
        />

        {file ? (
          <div className="flex items-center justify-center gap-2.5">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 6L9 17l-5-5" />
            </svg>
            <span className="truncate text-[13.5px] font-medium">{file.name}</span>
            <span className="text-[12px] text-fg-subtle">
              {(file.size / 1024).toFixed(0)} KB
            </span>
          </div>
        ) : (
          <>
            <svg
              className="mx-auto mb-2"
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="var(--fg-subtle)"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" />
            </svg>
            <div className="text-[13.5px] font-medium">
              Drop a PDF or <span className="text-accent">browse</span>
            </div>
            <div className="mt-0.5 text-[12px] text-fg-subtle">{hint}</div>
          </>
        )}
      </div>

      {error && (
        <p className="mt-1.5 text-[12.5px] font-medium text-danger">{error}</p>
      )}
    </div>
  );
}
