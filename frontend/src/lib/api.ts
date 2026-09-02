/** Typed client for the FolioProof backend. */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

// --- shapes returned by the backend ---------------------------------------

export type SourceId = "resume" | "github" | "linkedin" | "cover_letter";
/** Source precedence: earlier wins when facts conflict. */
export const SOURCE_PRIORITY: SourceId[] = ["resume", "linkedin", "github", "cover_letter"];

export interface PDFLocator {
  kind: "pdf";
  page: number;
  x0: number;
  top: number;
  x1: number;
  bottom: number;
  line_index: number | null;
}
export interface GitHubLocator {
  kind: "github";
  repo: string | null;
  field: string;
  url: string | null;
}
export interface TextLocator {
  kind: "text";
  start: number;
  end: number;
  section: string | null;
}
export type Locator = PDFLocator | GitHubLocator | TextLocator;

export interface EvidenceRef {
  source: SourceId;
  text: string;
  locator: Locator;
}

export interface SentenceRef {
  text: string;
  source: SourceId | null;
  note: string | null;
  evidence: EvidenceRef[];
}

export interface BlockRef {
  target: string;
  original: string;
  published: string;
  sentences: SentenceRef[];
}

export interface DocumentRef {
  source_id: SourceId;
  filename: string | null;
  stored_path: string | null;
  page_count: number;
  page_sizes: [number, number][];
}

export interface ProvenanceResponse {
  documents: DocumentRef[];
  blocks: BlockRef[];
}

export interface ConflictOption {
  value: string;
  evidence: EvidenceRef & { source_id?: SourceId; raw_text?: string };
}
export interface Conflict {
  id: string;
  field: string;
  description: string;
  options: { value: string; evidence: { source_id: SourceId; raw_text: string } }[];
  resolved_value: string | null;
}
export interface Gap {
  id: string;
  kind: string;
  description: string;
  claim_id: string | null;
}

export interface Metrics {
  claims: number;
  by_kind: Record<string, number>;
  multi_source_claims: number;
  conflicts: number;
  auto_resolved_conflicts: number;
  gaps: number;
  llm_calls: number;
  llm_available: boolean;
  top_repositories: number;
  sources_used: string[];
  about_words: number;
  hero_tagline: string;
  elapsed_seconds: number;
}

export interface BuildResponse {
  build_id: string;
  metrics: Metrics;
  warnings: string[];
  person: {
    name: string | null;
    headline: string | null;
    email: string | null;
    location: string | null;
    links: Record<string, string>;
  };
  conflicts: Conflict[];
  preview_url: string;
}

export interface GalleryImage {
  id: string;
  filename: string;
  original_name: string | null;
  caption: string;
  url: string;
  uploaded_at: string;
}

export interface Palette {
  bg: string;
  fg: string;
  accent: string;
  muted: string | null;
}
export interface ThemeInfo {
  key: string;
  label: string;
  description: string;
  palettes: Record<string, Palette>;
}
export interface ThemesResponse {
  sections: string[];
  themes: ThemeInfo[];
}

// --- calls -----------------------------------------------------------------

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function health() {
  return json<{
    status: string;
    groq_configured: boolean;
    github_token_configured: boolean;
    storage: string;
    source_priority: SourceId[];
  }>(await fetch(`${API_BASE}/health`, { cache: "no-store" }));
}

export async function getThemes() {
  return json<ThemesResponse>(
    await fetch(`${API_BASE}/api/themes`, { cache: "no-store" })
  );
}

export interface BuildPayload {
  resume: File;
  linkedin?: File | null;
  coverLetter?: File | null;
  githubUsername?: string;
  maxRepos?: number;
}

export async function buildProfile(payload: BuildPayload) {
  const form = new FormData();
  form.append("resume", payload.resume);
  if (payload.linkedin) form.append("linkedin", payload.linkedin);
  if (payload.coverLetter) form.append("cover_letter", payload.coverLetter);
  form.append("github_username", payload.githubUsername ?? "");
  form.append("max_repos", String(payload.maxRepos ?? 10));

  return json<BuildResponse>(
    await fetch(`${API_BASE}/api/build`, { method: "POST", body: form })
  );
}

export async function getProvenance(buildId: string) {
  return json<ProvenanceResponse>(
    await fetch(`${API_BASE}/api/profile/${buildId}/provenance`, {
      cache: "no-store",
    })
  );
}

export async function getProfile(buildId: string) {
  return json<{
    build_id: string;
    graph: { person: BuildResponse["person"]; conflicts: Conflict[]; gaps: Gap[] };
    analytics: Record<string, unknown> | null;
    metrics: Metrics;
    warnings: string[];
    theme: { theme: string; overrides: Record<string, Palette> };
  }>(
    await fetch(`${API_BASE}/api/profile/${buildId}`, { cache: "no-store" })
  );
}

export async function setTheme(
  buildId: string,
  theme: string,
  overrides: Record<string, Palette>
) {
  return json<{ ok: boolean }>(
    await fetch(`${API_BASE}/api/profile/${buildId}/theme`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme: { theme, overrides } }),
    })
  );
}

export async function resolveConflict(
  buildId: string,
  conflictId: string,
  value: string
) {
  return json<{ ok: boolean }>(
    await fetch(`${API_BASE}/api/profile/${buildId}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conflict_id: conflictId, value }),
    })
  );
}

// --- gallery (user uploads only) -------------------------------------------

export async function getGallery(buildId: string) {
  return json<{ gallery: GalleryImage[] }>(
    await fetch(`${API_BASE}/api/profile/${buildId}/gallery`, { cache: "no-store" })
  );
}

export async function uploadGalleryImages(
  buildId: string,
  files: File[],
  captions: string[] = []
) {
  const form = new FormData();
  files.forEach((f) => form.append("images", f));
  if (captions.length) form.append("captions", captions.join("\n"));

  return json<{ ok: boolean; added: number; gallery: GalleryImage[] }>(
    await fetch(`${API_BASE}/api/profile/${buildId}/gallery`, {
      method: "POST",
      body: form,
    })
  );
}

export async function updateGalleryCaption(
  buildId: string,
  imageId: string,
  caption: string
) {
  const form = new FormData();
  form.append("caption", caption);
  return json<{ ok: boolean; image: GalleryImage }>(
    await fetch(`${API_BASE}/api/profile/${buildId}/gallery/${imageId}`, {
      method: "PATCH",
      body: form,
    })
  );
}

export async function deleteGalleryImage(buildId: string, imageId: string) {
  return json<{ ok: boolean; gallery: GalleryImage[] }>(
    await fetch(`${API_BASE}/api/profile/${buildId}/gallery/${imageId}`, {
      method: "DELETE",
    })
  );
}

/** Gallery URLs come back relative to the API host. */
export const absoluteUrl = (path: string) =>
  path.startsWith("http") ? path : `${API_BASE}${path}`;

export const previewUrl = (buildId: string, bust = 0) =>
  `${API_BASE}/api/preview/${buildId}${bust ? `?v=${bust}` : ""}`;

/** Zipped static site: index.html + style.css + script.js + images/. */
export const exportUrl = (buildId: string) =>
  `${API_BASE}/api/export/${buildId}`;

export const pageImageUrl = (buildId: string, source: SourceId, page: number) =>
  `${API_BASE}/api/profile/${buildId}/page/${source}/${page}?scale=2`;
