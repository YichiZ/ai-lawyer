import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import CopyCitation from "@/app/laws/[slug]/[pinpoint]/CopyCitation";
import { formatDate, getCase } from "@/lib/api";

type Props = { params: Promise<{ slug: string }> };

const COURTS: Record<string, string> = { ONCA: "Court of Appeal for Ontario", SCC: "Supreme Court of Canada" };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const c = await getCase((await params).slug);
  return { title: c ? `${c.title}, ${c.citation.reference}` : "Not found" };
}

export default async function CasePage({ params }: Props) {
  const c = await getCase((await params).slug);
  if (!c) notFound();
  return (
    <article>
      <p className="pinpoint text-lg text-primary">{c.citation.reference}</p>
      <h1 className="font-serif text-3xl font-semibold italic">{c.title}</h1>
      <p className="mt-2 text-sm text-muted">
        {COURTS[c.court] ?? c.court} · {formatDate(c.date)} · Unofficial copy via A2AJ
        {c.url && (<>{" · "}<a href={c.url}>Official version</a></>)}
      </p>
      <p className="mt-1 text-xs text-muted">
        Ontario trial (Superior Court) decisions are not included in this guide. {c.upstream_license}
      </p>

      {c.plain_summary && (
        <aside className="mt-6 max-w-[68ch] border-l-2 border-primary pl-4" aria-labelledby="case-summary">
          <h2 id="case-summary" className="text-sm font-semibold">In plain language</h2>
          <p className="mt-1">{c.plain_summary}</p>
          <p className="mt-1 text-xs text-muted">AI-written, checked against the decision. Not legal advice.</p>
        </aside>
      )}

      <div className="mt-8 grid gap-8 lg:grid-cols-[1fr_16rem]">
        <div className="law-text">
          {c.paragraphs.map((p) => (
            <section key={p.pinpoint} id={p.pinpoint} className="mb-4 scroll-mt-20">
              <p className="pinpoint text-sm text-muted">[{p.display.replace("para ", "")}]</p>
              {p.lines.map((l, i) => <p key={i} data-level={l.level}>{l.text}</p>)}
            </section>
          ))}
        </div>
        <aside className="space-y-6 text-sm">
          {c.cites.statutes.length > 0 && (
            <section aria-labelledby="cites-laws">
              <h2 id="cites-laws" className="font-semibold">Laws cited</h2>
              <ul className="mt-1 space-y-1">{c.cites.statutes.map((s) => <li key={s.url}><Link href={s.url}>{s.label}</Link></li>)}</ul>
            </section>
          )}
          {c.cites.cases.length > 0 && (
            <section aria-labelledby="cites-cases">
              <h2 id="cites-cases" className="font-semibold">Cases cited</h2>
              <ul className="mt-1 space-y-1">
                {c.cites.cases.map((x) => (
                  <li key={x.citation}>{x.url ? <Link href={x.url}>{x.title ? <cite className="italic">{x.title}</cite> : x.citation}{x.title && `, ${x.citation}`}</Link> : <span className="text-muted">{x.citation}</span>}</li>
                ))}
              </ul>
            </section>
          )}
          {c.cited_by.length > 0 && (
            <section aria-labelledby="cited-by">
              <h2 id="cited-by" className="font-semibold">Cited by</h2>
              <ul className="mt-1 space-y-1">{c.cited_by.map((x) => <li key={x.citation}><Link href={x.url}><cite className="italic">{x.title}</cite>, {x.citation}</Link></li>)}</ul>
            </section>
          )}
        </aside>
      </div>
      <CopyCitation title={c.citation.title} reference={c.citation.reference} text={c.citation.text} />
    </article>
  );
}
