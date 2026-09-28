import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import CitationChips from "@/components/CitationChips";
import Markdown from "@/components/Markdown";
import SourceList from "@/components/SourceList";
import WebSources from "@/components/WebSources";
import WebFallback from "./WebFallback";
import { REJECT_REASONS, formatTimestamp, getAnswer } from "@/lib/api";
import { currentRole } from "@/lib/role";

export const metadata: Metadata = { title: "Research answer" };

type Props = { params: Promise<{ id: string }> };

export default async function AnswerPage({ params }: Props) {
  const id = Number((await params).id);
  if (!Number.isInteger(id) || id < 1) notFound();
  const a = await getAnswer(id, await currentRole());
  if (!a) notFound();
  const released = a.status === "approved" || a.status === "edited";

  return (
    <div className="max-w-3xl">
      <p className="text-sm text-muted">Research question</p>
      <h1 className="font-serif text-2xl font-semibold">{a.question}</h1>

      <section aria-labelledby="answer-heading" className="mt-6 rounded-sm border border-rule bg-panel p-5">
        <h2 id="answer-heading" className="font-semibold">Answer</h2>
        {a.status === "pending_review" && (
          <p className="mt-2" role="status">
            <strong>Awaiting review.</strong> A reviewer checks every answer against the law before it is released.{" "}
            <Link href={`/answers/${a.id}`}>Refresh</Link>
          </p>
        )}
        {a.status === "pending_review" && !a.library_match && !a.web_fallback && <WebFallback question={a.question} />}
        {a.web_fallback && <p className="mt-2 text-sm font-semibold text-accent">Web search answer — not from our law library.</p>}
        {released && (
          <>
            <div className="mt-3">
              <Markdown text={a.final_markdown ?? ""} />
            </div>
            <WebSources sources={a.web_sources ?? []} />
            {a.claims && a.claims.length > 0 && <CitationChips claims={a.claims} />}
            <p className="mt-4 text-sm text-muted">
              Reviewed by {a.reviewed_by} on {formatTimestamp(a.reviewed_at)}
              {a.edited && " (edited by reviewer)"}. Research aid only — not legal advice.
            </p>
          </>
        )}
        {a.status === "rejected" && (
          <p className="mt-2">
            A reviewer did not release this answer ({REJECT_REASONS[a.review_reason ?? ""] ?? a.review_reason}). The
            sources below may still help.
          </p>
        )}
      </section>

      <section aria-labelledby="sources-heading" className="mt-8">
        <h2 id="sources-heading" className="font-serif text-xl font-semibold">Sources found</h2>
        <SourceList sources={a.sources} />
      </section>
    </div>
  );
}
