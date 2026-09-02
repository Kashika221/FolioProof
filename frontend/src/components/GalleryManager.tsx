"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Banner, Spinner } from "@/components/ui";
import {
  type GalleryImage,
  absoluteUrl,
  deleteGalleryImage,
  getGallery,
  updateGalleryCaption,
  uploadGalleryImages,
} from "@/lib/api";

const MAX_IMAGES = 24;
const MAX_BYTES = 5 * 1024 * 1024;
const ACCEPT = [".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"];

/**
 * Gallery images are uploaded by the user and nothing else.
 *
 * Nothing here fetches from LinkedIn, GitHub or any other service: LinkedIn
 * exposes no public API for post media and scraping it is against their terms,
 * so the only honest source is the person whose portfolio this is.
 */
export function GalleryManager({
  buildId,
  onChanged,
}: {
  buildId: string;
  onChanged: () => void;
}) {
  const [images, setImages] = useState<GalleryImage[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getGallery(buildId)
      .then((r) => setImages(r.gallery))
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load gallery"))
      .finally(() => setLoading(false));
  }, [buildId]);

  const upload = useCallback(
    async (fileList: FileList | null) => {
      if (!fileList?.length) return;
      setError(null);

      const files = Array.from(fileList);
      const bad = files.find(
        (f) => !ACCEPT.some((ext) => f.name.toLowerCase().endsWith(ext))
      );
      if (bad) {
        setError(`${bad.name} is not an image (${ACCEPT.join(", ")}).`);
        return;
      }
      const tooBig = files.find((f) => f.size > MAX_BYTES);
      if (tooBig) {
        setError(`${tooBig.name} is over 5 MB.`);
        return;
      }
      if (images.length + files.length > MAX_IMAGES) {
        setError(
          `That would exceed ${MAX_IMAGES} images (${images.length} already uploaded).`
        );
        return;
      }

      setBusy(true);
      try {
        // Default each caption to the filename; the user can edit after upload.
        const captions = files.map((f) =>
          f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ")
        );
        const res = await uploadGalleryImages(buildId, files, captions);
        setImages(res.gallery);
        onChanged();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Upload failed");
      } finally {
        setBusy(false);
        if (inputRef.current) inputRef.current.value = "";
      }
    },
    [buildId, images.length, onChanged]
  );

  async function remove(id: string) {
    setBusy(true);
    try {
      const res = await deleteGalleryImage(buildId, id);
      setImages(res.gallery);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }

  async function saveCaption(id: string) {
    const caption = draft.trim();
    setEditing(null);
    const previous = images;
    setImages((gs) => gs.map((g) => (g.id === id ? { ...g, caption } : g)));
    try {
      await updateGalleryCaption(buildId, id, caption);
      onChanged();
    } catch (e) {
      setImages(previous);
      setError(e instanceof Error ? e.message : "Could not save caption");
    }
  }

  if (loading) {
    return (
      <div className="grid gap-3 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="skeleton h-40 rounded-2xl" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          upload(e.dataTransfer.files);
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
        aria-label="Upload gallery images"
        className="cursor-pointer rounded-2xl border-2 border-dashed p-8 text-center transition-all"
        style={{
          borderColor: over ? "var(--accent)" : "var(--border-strong)",
          background: over ? "var(--accent-tint)" : "var(--bg)",
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT.join(",")}
          multiple
          className="hidden"
          onChange={(e) => upload(e.target.files)}
        />
        {busy ? (
          <div className="flex items-center justify-center gap-2 text-[14px]">
            <Spinner /> Uploading…
          </div>
        ) : (
          <>
            <svg
              className="mx-auto mb-2"
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="var(--fg-subtle)"
              strokeWidth="1.7"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <circle cx="8.5" cy="8.5" r="1.5" />
              <path d="M21 15l-5-5L5 21" />
            </svg>
            <div className="text-[14px] font-medium">
              Drop images or <span className="text-accent">browse</span>
            </div>
            <div className="mt-1 text-[12.5px] text-fg-subtle">
              {ACCEPT.join(", ")} · up to 5 MB each · {images.length}/{MAX_IMAGES} used
            </div>
          </>
        )}
      </div>

      {error && (
        <p className="rounded-xl bg-danger-tint px-3.5 py-2.5 text-[13px] font-medium text-danger">
          {error}
        </p>
      )}

      {images.length === 0 ? (
        <Banner tone="info" title="Your gallery is empty">
          Add photos of hackathons, demos, talks or team moments. These are
          uploaded by you — FolioProof does not pull images from LinkedIn or any
          other site.
        </Banner>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {images.map((img) => (
            <figure key={img.id} className="card overflow-hidden">
              <div className="relative">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={absoluteUrl(img.url)}
                  alt={img.caption || "Gallery image"}
                  className="aspect-video w-full object-cover"
                  loading="lazy"
                />
                <button
                  onClick={() => remove(img.id)}
                  disabled={busy}
                  aria-label={`Remove ${img.caption || "image"}`}
                  className="absolute right-2 top-2 rounded-full bg-black/65 p-1.5 text-white transition hover:bg-danger"
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                    <path d="M18 6L6 18M6 6l12 12" />
                  </svg>
                </button>
              </div>

              <figcaption className="p-3">
                {editing === img.id ? (
                  <input
                    autoFocus
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onBlur={() => saveCaption(img.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") saveCaption(img.id);
                      if (e.key === "Escape") setEditing(null);
                    }}
                    className="field !py-1.5 !text-[13px]"
                    placeholder="Caption"
                  />
                ) : (
                  <button
                    onClick={() => {
                      setEditing(img.id);
                      setDraft(img.caption);
                    }}
                    className="w-full truncate text-left text-[13px] font-medium hover:text-accent"
                    title="Click to edit caption"
                  >
                    {img.caption || (
                      <span className="text-fg-subtle">Add a caption…</span>
                    )}
                  </button>
                )}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </div>
  );
}
