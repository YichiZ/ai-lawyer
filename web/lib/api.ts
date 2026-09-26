// Typed client for the FastAPI backend. Server-side only (called from Server Components).
const API_URL = process.env.API_URL ?? "http://localhost:8000";

export type Kind = "statute" | "regulation" | "bylaw" | "decision";

export interface DocumentSummary {
  slug: string;
  title: string;
  short_name: string | null;
  citation: string | null;
  kind: Kind;
  in_force_from: string | null;
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

export interface Section extends SectionRef {
  text: string;
  lines: { text: string; level: number }[];
  full_text: boolean;
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

async function get<T>(path: string): Promise<T | null> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  } catch (err) {
    console.error(`API unreachable at ${API_URL}${path}`, err);
    throw new ApiError(503, "The law library is unavailable right now.");
  }
  if (res.status === 404 || res.status === 422) return null;
  const body = (await res.json()) as Envelope<T>;
  if (!res.ok || body.error) {
    console.error(`API error ${res.status} on ${path}`, body.error);
    throw new ApiError(res.status, body.error?.message ?? "Unexpected error.");
  }
  return body.data;
}

export const listLaws = () => get<{ kind: Kind; documents: DocumentSummary[] }[]>("/laws");
export const getLaw = (slug: string) => get<{ document: DocumentMeta; tree: TreeNode[] }>(`/laws/${encodeURIComponent(slug)}`);
export const getSection = (slug: string, pinpoint: string) =>
  get<Section>(`/laws/${encodeURIComponent(slug)}/${encodeURIComponent(pinpoint)}`);

export const KIND_LABELS: Record<Kind, string> = {
  statute: "Statutes",
  regulation: "Regulations",
  bylaw: "Toronto by-laws",
  decision: "Decisions",
};

export function formatDate(iso: string | null): string {
  if (!iso) return "unknown date";
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-CA", { year: "numeric", month: "long", day: "numeric" });
}

export function sourceLabel(doc: DocumentMeta): string {
  return doc.source === "a2aj-laws" ? "Ontario e-Laws via A2AJ" : "City of Toronto";
}
