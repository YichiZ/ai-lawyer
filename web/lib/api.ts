// Typed client for the FastAPI backend. Server-side only (called from Server Components).
const API_URL = process.env.API_URL ?? "http://localhost:8000";

export type Kind = "statute" | "regulation" | "bylaw" | "decision" | "web";

export interface DocumentSummary {
  slug: string;
  title: string;
  short_name: string | null;
  citation: string | null;
  kind: Kind;
  in_force_from: string | null;
  date: string | null; // web pages: the day the page was fetched
  subtitle: string | null; // citation, or a web page's domain
  reproduction: "full" | "excerpt";
  section_count: number;
}

export interface DocumentMeta extends Omit<DocumentSummary, "section_count"> {
  jurisdiction: string;
  url: string | null;
  source: string;
  upstream_license: string | null;
}

export interface TreeNode {
  pinpoint: string;
  display: string;
  kind: "part" | "section";
  heading: string | null;
  parent: string | null;
}

export interface SectionRef {
  pinpoint: string;
  display: string;
  kind: string;
  heading: string | null;
}

export interface GlossaryEntry {
  term: string;
  definition: string;
  source: { url: string; display: string } | null;
}

export interface Section extends SectionRef {
  text: string;
  lines: { text: string; level: number; note?: string | null }[];  // note: the subsection marginal note that opens this line
  full_text: boolean;
  plain_summary: string | null;
  glossary: GlossaryEntry[];
  cited_by: { total: number; decisions: { title: string; citation: string; url: string; pinpoints: string[] }[] };
  citation: { title: string; reference: string; text: string };
  breadcrumb: SectionRef[];
  children: (SectionRef & { text: string })[];
  prev: string | null;
  next: string | null;
  document: DocumentMeta;
}

interface Envelope<T> {
  data: T | null;
  error: { code: string; message: string } | null;
  meta: Record<string, unknown> | null;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export type Role = "researcher" | "reviewer";

async function requestEnvelope<T>(path: string, init: RequestInit = {}, role?: Role): Promise<Envelope<T> | null> {
  let res: Response;
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (role) headers["X-Demo-User"] = role;
  try {
    res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init, headers });
  } catch (err) {
    console.error(`API unreachable at ${API_URL}${path}`, err);
    throw new ApiError(503, "The law library is unavailable right now.");
  }
  if (res.status === 404 || (res.status === 422 && !init.method)) return null;
  const body = (await res.json()) as Envelope<T>;
  if (!res.ok || body.error) {
    console.error(`API error ${res.status} on ${path}`, body.error);
    throw new ApiError(res.status, body.error?.message ?? "Unexpected error.");
  }
  return body;
}

async function request<T>(path: string, init: RequestInit = {}, role?: Role): Promise<T | null> {
  return (await requestEnvelope<T>(path, init, role))?.data ?? null;
}

const get = <T,>(path: string, role?: Role) => request<T>(path, {}, role);
const post = <T,>(path: string, body: unknown, role: Role) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) }, role);

export const listLaws = () => get<{ kind: Kind; documents: DocumentSummary[] }[]>("/laws");
export const getLaw = (slug: string) => get<{ document: DocumentMeta; tree: TreeNode[] }>(`/laws/${encodeURIComponent(slug)}`);
export const getSection = (slug: string, pinpoint: string) =>
  get<Section>(`/laws/${encodeURIComponent(slug)}/${encodeURIComponent(pinpoint)}`);

export interface Source {
  chunk_id: string;
  slug: string;
  title: string;
  pinpoint: string;
  display: string;
  citation: { title: string; reference: string; text: string };
  snippet: string;
  url: string;
  score?: number | null;
  distance?: number | null;
  referenced_by_display?: string | null; // a provision another source refers to (#61)
}

export interface Claim {
  text: string;
  chunk_id: string;
  quote: string;
  source: Source;
  reason?: string;
}

export interface Answer {
  id: number;
  question: string;
  status: "pending_review" | "approved" | "edited" | "rejected";
  created_at: string;
  sources: Source[];
  web_fallback: boolean;
  library_match: boolean;
  message?: string;
  final_markdown?: string;
  claims?: Claim[];
  edited?: boolean;
  reviewed_by?: string;
  reviewed_at?: string;
  review_reason?: string;
  draft_markdown?: string;
  review_note?: string;
  risk?: string[];
  dropped_claims?: Claim[];
}

export interface QueueItem {
  id: number;
  question: string;
  draft_markdown: string;
  claims: Claim[];
  created_at: string;
  asked_by: string | null;
  risk: string[];
  draft_status: string;
  dropped_claims: Claim[];
  sources: Source[];
  web_sources: { url: string; title: string; domain: string; addable: boolean }[];
  trace_url: string | null;
  guide: { slug: string; title: string; heading: string } | null;
}

export interface IngestJob {
  id: string;
  url: string;
  status: "queued" | "running" | "done" | "dead";
  stage: string | null;
  error: string | null;
  document_slug: string | null;
}

export const ask = (question: string, role: Role) =>
  post<{ answer_id: number; status: string; sources: Source[] }>("/ask", { question }, role);
export const askWeb = (question: string, role: Role) =>
  post<{ answer_id: number; status: string }>("/ask/web", { question }, role);
export const ingestUrl = (url: string, inScope: boolean, role: Role) =>
  post<IngestJob>("/ingest", { url, in_scope: inScope }, role);
export const getIngestJob = (id: string) => get<IngestJob>(`/ingest/${id}`, "reviewer");
export const getAnswer = (id: number, role: Role) => get<Answer>(`/answers/${id}`, role);
export const getQueue = (role: Role) => get<QueueItem[]>("/review/queue", role);
export const reviewAnswer = (id: number, body: Record<string, string>, role: Role) =>
  post<{ id: number; status: string }>(`/answers/${id}/review`, body, role);

export interface Suggestion {
  type: "law" | "section" | "case";
  slug: string;
  title: string;
  display: string | null;
  heading: string | null;
  url: string;
}

export interface SearchGroup {
  slug: string;
  title: string;
  kind: Kind;
  subtitle: string | null;
  hits: { pinpoint: string; display: string; citation: Source["citation"]; snippet: string; url: string }[];
}

export interface GuideSummary {
  slug: string;
  title: string;
  intro: string;
  sections: number;
  reviewed: number;
}

export interface GuideSection {
  heading: string;
  question: string;
  answer_id: number | null;
  status: string;
  final_markdown?: string;
  claims?: Claim[];
  reviewed_by?: string;
  reviewed_at?: string;
  edited?: boolean;
  sources?: Source[]; // pending sections only: what retrieval found, never the draft
}

export interface Case {
  slug: string;
  title: string;
  court: string;
  date: string;
  url: string | null;
  upstream_license: string | null;
  plain_summary: string | null;
  citation: { title: string; reference: string; text: string };
  intro: string | null;
  paragraphs: { pinpoint: string; display: string; lines: { text: string; level: number }[] }[];
  cites: { statutes: { label: string; url: string }[]; cases: { citation: string; title: string | null; url: string | null }[] };
  cited_by: { citation: string; title: string; url: string }[];
}

export const getCase = (slug: string) => get<Case>(`/cases/${encodeURIComponent(slug)}`);
export const listGuides = () => get<GuideSummary[]>("/guides");
export const getGuide = (slug: string) =>
  get<{ slug: string; title: string; intro: string; sections: GuideSection[] }>(`/guides/${encodeURIComponent(slug)}`);
export const getGlossary = () => get<GlossaryEntry[]>("/glossary");
export const listRecentAnswers = (limit = 5) =>
  get<{ id: number; question: string; reviewed_by: string | null; reviewed_at: string }[]>(`/answers?limit=${limit}`);
export const suggest = (q: string) => get<Suggestion[]>(`/suggest?q=${encodeURIComponent(q)}`);

// Fused order (fast); `rerank` asks for the same hits in the reranked order, which takes ~1.5 s (#41).
export async function search(q: string, rerank = false): Promise<{ groups: SearchGroup[]; askThis: boolean }> {
  const path = `/search?q=${encodeURIComponent(q)}${rerank ? "&rerank=true" : ""}`;
  const body = await requestEnvelope<SearchGroup[]>(path);  // 422 (bad query) -> null
  return { groups: body?.data ?? [], askThis: Boolean(body?.meta?.ask_this) };
}

export const REJECT_REASONS: Record<string, string> = {
  wrong_law: "Wrong law",
  missing_authority: "Missing authority",
  unsupported_claim: "Unsupported claim",
  out_of_scope: "Out of scope",
  legal_advice: "Gives legal advice",
};

export const KIND_LABELS: Record<Kind, string> = {
  statute: "Statutes",
  regulation: "Regulations",
  bylaw: "Toronto by-laws",
  decision: "Decisions",
  web: "Official web pages",
};

export function formatDate(iso: string | null): string {
  if (!iso) return "unknown date";
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-CA", { year: "numeric", month: "long", day: "numeric" });
}

/** "as of <in-force date>" for laws; "fetched <date>" for web pages, which have no in-force date. */
export function asOf(doc: Pick<DocumentSummary, "kind" | "in_force_from" | "date">): string {
  return doc.kind === "web" ? `fetched ${formatDate(doc.date)}` : `as of ${formatDate(doc.in_force_from)}`;
}

export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "unknown date";
  return new Date(iso).toLocaleDateString("en-CA", {
    year: "numeric", month: "long", day: "numeric", timeZone: "America/Toronto",
  });
}

export function sourceLabel(doc: DocumentMeta): string {
  if (doc.source === "a2aj-laws") return "Ontario e-Laws via A2AJ";
  if (doc.source === "toronto-municipal-code") return "City of Toronto";
  return doc.source.startsWith("web:") ? doc.source.slice(4) : doc.source;  // web:ontario.ca -> ontario.ca
}
