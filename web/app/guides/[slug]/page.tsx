import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import CitationChips from "@/components/CitationChips";
import Markdown from "@/components/Markdown";
import SourceList from "@/components/SourceList";
import { formatTimestamp, getGuide } from "@/lib/api";

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const g = await getGuide((await params).slug);
  return { title: g?.title ?? "Not found" };
}

export default async function GuidePage({ params }: Props) {
  const { slug } = await params;
  const guide = await getGuide(slug);
  if (!guide) notFound();
  return (
    <article className="max-w-3xl">
      <p className="text-sm"><Link href="/">Topic guides</Link></p>
      <h1 className="mt-2 font-serif text-3xl font-semibold">{guide.title}</h1>
      <p className="mt-2 text-lg text-muted">{guide.intro}</p>
      <p className="mt-2 text-sm text-muted">Rules, not advice. Deadlines are stated as the law writes them — this guide does not calculate dates.</p>

      {guide.sections.map((s, i) => (
        <section key={s.heading} className="mt-10" aria-labelledby={`sec-${i}`}>
          <h2 id={`sec-${i}`} className={`font-serif text-2xl font-semibold ${i === 0 ? "text-accent" : ""}`}>{s.heading}</h2>
          <p className="mt-1 text-sm text-muted">{s.question}</p>
          {s.final_markdown ? (
            <div className="mt-3">
              <Markdown text={s.final_markdown} />
              {s.claims && s.claims.length > 0 && <CitationChips claims={s.claims} />}
              <p className="mt-3 text-xs text-muted">
                Reviewed by {s.reviewed_by} on {formatTimestamp(s.reviewed_at)}{s.edited && " (edited by reviewer)"}.
              </p>
            </div>
          ) : (
            <div className="mt-3">
              <p className="rounded-sm border border-rule bg-panel p-3 text-sm">
                Awaiting review.{s.sources && s.sources.length > 0 && " Until a reviewer approves the answer, these are the sources found for this question."}
              </p>
              {s.sources && s.sources.length > 0 && (
                <>
                  <h3 className="sr-only">Sources found for {s.heading}</h3>
                  <SourceList sources={s.sources} />
                </>
              )}
            </div>
          )}
        </section>
      ))}

      <section className="mt-12 border-t border-rule pt-6" aria-labelledby="ask-heading">
        <h2 id="ask-heading" className="font-serif text-xl font-semibold">Ask about {guide.title.toLowerCase()}</h2>
        <form action="/ask" className="mt-3 flex flex-wrap gap-2">
          <label htmlFor="guide-q" className="sr-only">Your question</label>
          <input id="guide-q" name="q" required minLength={5} className="min-w-0 flex-1 rounded-sm border border-rule bg-panel px-3 py-2"
                 placeholder={guide.sections[0]?.question ?? "Your question"} />
          <button type="submit" className="rounded-sm bg-primary px-4 py-2 font-semibold text-paper">Continue</button>
        </form>
      </section>
    </article>
  );
}
