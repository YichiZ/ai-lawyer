"use server";

import { refresh } from "next/cache";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ApiError, ask, getSection, reviewAnswer } from "@/lib/api";
import { ROLE_COOKIE, currentRole } from "@/lib/role";

export type FormState = { error?: string };

export async function setRole(role: "researcher" | "reviewer") {
  (await cookies()).set(ROLE_COOKIE, role, { sameSite: "lax", path: "/" });
  refresh();
}

export async function askAction(_: FormState, form: FormData): Promise<FormState> {
  const question = String(form.get("question") ?? "").trim();
  if (question.length < 5) return { error: "Please write a question of at least 5 characters." };
  if (question.length > 1000) return { error: "Please keep the question under 1,000 characters." };
  let answerId: number;
  try {
    const res = await ask(question, await currentRole());
    if (!res) return { error: "The question could not be submitted." };
    answerId = res.answer_id;
  } catch (err) {
    return { error: err instanceof ApiError ? err.message : "The question could not be submitted. Please try again." };
  }
  redirect(`/answers/${answerId}`);
}

export async function reviewAction(answerId: number, _: FormState, form: FormData): Promise<FormState> {
  const decision = String(form.get("decision") ?? "");
  const body: Record<string, string> = { decision };
  if (decision === "edit") {
    body.final_markdown = String(form.get("final_markdown") ?? "").trim();
    body.note = String(form.get("note") ?? "").trim();
    if (!body.final_markdown || !body.note) return { error: "An edit needs the revised answer and a note explaining it." };
  }
  if (decision === "reject") {
    body.reason = String(form.get("reason") ?? "");
    if (!body.reason) return { error: "Choose a reason for rejecting." };
  }
  try {
    await reviewAnswer(answerId, body, await currentRole());
  } catch (err) {
    return { error: err instanceof ApiError ? err.message : "The decision could not be saved. Please try again." };
  }
  refresh();
  return {};
}

export type Passage = { display: string; title: string; text: string; fullText: boolean; href: string };

export async function loadPassage(slug: string, pinpoint: string): Promise<Passage | null> {
  // Chunk pinpoints may be a subsection (s-4-1); the API enforces the excerpt-only rule for City by-laws.
  const s = await getSection(slug, pinpoint);
  if (!s) return null;
  return {
    display: s.display,
    title: s.document.short_name ?? s.document.title,
    text: s.lines.map((l) => l.text).join(" "),
    fullText: s.full_text,
    href: `/laws/${slug}/${pinpoint}`,
  };
}
